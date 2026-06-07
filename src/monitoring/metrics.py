import asyncio
import json
import logging
from collections import Counter, deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.monitoring.metrics_store import MetricsStore

logger = logging.getLogger("monitoring.metrics")


# ---------------------------------------------------------------------------
# MetricsCollector: in-memory counters + optional SQLite-backed store
# ---------------------------------------------------------------------------
# Counters in this class are the source of truth for ``prometheus_text()``
# (kept fast: a Counter increment is O(1)). When a MetricsStore is attached,
# every increment is also appended to ``_pending_writes`` and flushed to
# SQLite every 10 seconds (and on shutdown). On startup, the last 30 days
# of stored counters are loaded back into the in-memory Counters so the
# Prometheus endpoint survives a process restart.


class MetricsCollector:
    def __init__(
        self,
        max_history: int = 1000,
        store: "MetricsStore | None" = None,
        flush_interval_s: float = 10.0,
    ):
        self._event_counter: Counter[str] = Counter()
        self._signal_counter: Counter[str] = Counter()
        self._order_counter: Counter[str] = Counter()
        self._error_counter: Counter[str] = Counter()
        self._latency_history: deque[float] = deque(maxlen=max_history)
        self._event_rate_history: deque[float] = deque(maxlen=100)
        self._start_time: float = 0.0

        # Persistence layer (opt-in; default = no persistence)
        self._store: MetricsStore | None = store
        self._pending_writes: list[tuple[str, dict[str, str], float]] = []
        self._flush_interval_s = flush_interval_s
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()

    # ----- Lifecycle ----------------------------------------------------

    def start(self) -> None:
        """Initialize uptime counter and start the periodic flush task.

        The flush task is best-effort: it only starts if a store is
        attached AND an asyncio event loop is already running. In
        sync contexts (rare; mostly tests), ``flush()`` can be called
        manually.
        """
        import time

        self._start_time = time.time()
        if self._store is None or self._flush_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._flush_task = loop.create_task(self._periodic_flush_loop())

    async def stop(self) -> None:
        """Cancel the flush task and do a final flush to the store."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
            self._flush_task = None
        await self.flush()

    async def load_from_store(
        self, window_seconds: int = 30 * 24 * 3600
    ) -> dict[str, int]:
        """Repopulate in-memory counters from the durable store.

        Returns the number of distinct (metric, labels) tuples
        loaded per counter, for observability in startup logs.
        """
        if self._store is None:
            return {}
        totals = await self._store.load_recent_totals(window_seconds)
        loaded: dict[str, int] = {}
        for (metric, labels_json), value in totals.items():
            try:
                labels = json.loads(labels_json)
            except json.JSONDecodeError:
                continue
            iv = int(value)
            if metric == "trading_events_total":
                self._event_counter[labels.get("type", "")] += iv
            elif metric == "trading_signals_total":
                key = f"{labels.get('strategy', '')}:{labels.get('direction', '')}"
                self._signal_counter[key] += iv
            elif metric == "trading_orders_total":
                self._order_counter[labels.get("status", "")] += iv
            elif metric == "trading_errors_total":
                self._error_counter[labels.get("component", "")] += iv
            else:
                # Unknown metric (forward-compat); ignore
                continue
            loaded[metric] = loaded.get(metric, 0) + 1
        return loaded

    async def _periodic_flush_loop(self) -> None:
        """Background task: flush every ``flush_interval_s`` seconds."""
        while True:
            try:
                await asyncio.sleep(self._flush_interval_s)
            except asyncio.CancelledError:
                break
            try:
                await self.flush()
            except Exception as exc:  # pragma: no cover - logged not raised
                logger.warning("Periodic metrics flush failed: %s", exc)

    async def flush(self) -> None:
        """Flush pending counter increments to the store, if attached."""
        if self._store is None or not self._pending_writes:
            return
        # Snapshot the buffer; new writes go to a fresh list while
        # we flush the old one (keeps the hot path lock-free).
        pending = self._pending_writes
        self._pending_writes = []
        try:
            async with self._flush_lock:
                for metric, labels, delta in pending:
                    await self._store.increment(metric, labels, delta)
                await self._store.flush()
        except Exception as exc:
            logger.warning(
                "Metrics flush failed; re-buffering %d writes: %s",
                len(pending),
                exc,
            )
            # Re-buffer so transient errors don't lose data
            self._pending_writes.extend(pending)

    def attach_store(self, store: "MetricsStore | None") -> None:
        """Attach (or detach) a persistence store at runtime.

        Idempotent. If a flush task is already running it is left
        alone; the new store will be picked up on the next flush
        cycle. This is the hook called by ``src/main.py`` to wire
        up production persistence; tests use the
        ``isolated_metrics_store`` autouse fixture in
        ``tests/conftest.py`` instead.
        """
        self._store = store
        # If a flush task is already scheduled, leave it running —
        # it will start writing to the new store on its next tick.
        # If there is no task and a store was just attached, the
        # caller should invoke ``start()`` to schedule one.

    # ----- Hot-path counter API (sync; matches existing call sites) -----

    def count_event(self, event_type: str) -> None:
        self._event_counter[event_type] += 1
        if self._store is not None:
            self._pending_writes.append(
                ("trading_events_total", {"type": event_type}, 1.0)
            )

    def count_signal(self, strategy: str, direction: str) -> None:
        self._signal_counter[f"{strategy}:{direction}"] += 1
        if self._store is not None:
            self._pending_writes.append(
                (
                    "trading_signals_total",
                    {"strategy": strategy, "direction": direction},
                    1.0,
                )
            )

    def count_order(self, status: str) -> None:
        self._order_counter[status] += 1
        if self._store is not None:
            self._pending_writes.append(
                ("trading_orders_total", {"status": status}, 1.0)
            )

    def count_error(self, component: str) -> None:
        self._error_counter[component] += 1
        if self._store is not None:
            self._pending_writes.append(
                ("trading_errors_total", {"component": component}, 1.0)
            )

    def record_latency(self, seconds: float) -> None:
        self._latency_history.append(seconds)
        # Latency is not persisted: it's a rolling window by design
        # (gauge-like, not a counter). If we ever need historical
        # latency percentiles, store as a gauge histogram.

    # ----- Read-side helpers (unchanged interface) ---------------------

    def _connection_active(self, target: Any) -> bool:
        connection_state = getattr(target, "is_connected", None)
        if connection_state is None:
            return False
        try:
            if callable(connection_state):
                connection_state = connection_state()
        except Exception as exc:
            logger.warning("Failed to read broker connection state: %s", exc)
            return False
        return bool(connection_state)

    def snapshot(self) -> dict[str, Any]:
        import time

        uptime = time.time() - self._start_time if self._start_time > 0 else 0
        total_events = sum(self._event_counter.values())
        return {
            "uptime_seconds": uptime,
            "total_events": total_events,
            "events_by_type": dict(self._event_counter),
            "signals_by_strategy": dict(self._signal_counter),
            "orders_by_status": dict(self._order_counter),
            "errors_by_component": dict(self._error_counter),
            "avg_latency_ms": (
                (sum(self._latency_history) / len(self._latency_history) * 1000)
                if self._latency_history
                else 0
            ),
            "event_rate": total_events / uptime if uptime > 0 else 0,
        }

    def prometheus_text(self, system=None) -> str:
        snapshot = self.snapshot()
        lines = [
            "# HELP trading_events_total Total events processed",
            "# TYPE trading_events_total counter",
        ]
        for etype, count in snapshot["events_by_type"].items():
            safe = etype.replace(".", "_")
            lines.append(f'trading_events_total{{type="{safe}"}} {count}')

        lines.extend(
            [
                "",
                "# HELP trading_signals_total Signals generated by strategy",
                "# TYPE trading_signals_total counter",
            ]
        )
        for strat, count in snapshot["signals_by_strategy"].items():
            safe = strat.replace(":", "_").replace(".", "_")
            lines.append(f'trading_signals_total{{strategy="{safe}"}} {count}')

        lines.extend(
            [
                "",
                "# HELP trading_orders_total Orders by status",
                "# TYPE trading_orders_total counter",
            ]
        )
        for status, count in snapshot["orders_by_status"].items():
            lines.append(f'trading_orders_total{{status="{status}"}} {count}')

        # Add Kill Switch metric
        from src.risk.kill_switch import KillSwitch

        kill_active = 1 if KillSwitch().active else 0

        # Add Broker Connected metric
        broker_connected = 0
        if (
            system
            and hasattr(system, "execution")
            and system.execution
            and hasattr(system.execution, "_broker")
            and system.execution._broker
        ):
            broker = system.execution._broker
            if self._connection_active(broker):
                broker_connected = 1
            elif hasattr(broker, "_client") and self._connection_active(broker._client):
                broker_connected = 1

        lines.extend(
            [
                "",
                "# HELP trading_errors_total Errors by component",
                "# TYPE trading_errors_total counter",
                f'trading_errors_total {{component="all"}} {sum(snapshot["errors_by_component"].values())}',
                "",
                f"trading_uptime_seconds {snapshot['uptime_seconds']}",
                f"trading_avg_latency_ms {snapshot['avg_latency_ms']}",
                f"trading_event_rate {snapshot['event_rate']}",
                f"trading_kill_switch_active {kill_active}",
                f"trading_broker_connected {broker_connected}",
            ]
        )
        return "\n".join(lines) + "\n"


# Module-level singleton. The store is wired up at process startup
# by src/main.py (see ``system_metrics.attach_store(...)``). Tests
# that need persistence use the ``isolated_metrics_store`` autouse
# fixture in tests/conftest.py.
system_metrics = MetricsCollector()
