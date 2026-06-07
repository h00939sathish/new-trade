import asyncio
import json
import logging
import time
from collections import Counter, deque
from datetime import date
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
#
# Gauges (portfolio state: PnL, exposure, drawdown, etc.) live in plain
# attributes and are updated via ``update_portfolio_state`` (1-Hz
# throttled writes to the store). Gauges are intentionally not restored
# on startup: a portfolio agent re-emits them on the next portfolio
# update, and a stale last-write-wins value would be misleading.


# Default throttle for portfolio-state gauge writes. Plan constraint:
# "Do NOT call these on every event (use a 1-second cache to avoid hot
# loop)". 1 Hz is fine for a Prometheus scrape interval of 15s+ and
# keeps the write rate to ~5 samples per minute per gauge.
_PORTFOLIO_FLUSH_THROTTLE_S = 1.0


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

        self._pnl_daily: float = 0.0
        self._exposure_total: float = 0.0
        self._open_positions: int = 0
        self._drawdown_pct: float = 0.0
        self._peak_capital: float = 0.0
        self._pnl_daily_baseline: float = 0.0
        self._pnl_daily_reset_day: date | None = None

        # Persistence layer (opt-in; default = no persistence)
        self._store: MetricsStore | None = store
        self._pending_writes: list[tuple[str, dict[str, str], float]] = []
        self._pending_gauge_writes: list[tuple[str, float, dict[str, str]]] = []
        self._flush_interval_s = flush_interval_s
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()
        self._last_portfolio_flush_ts: float = 0.0

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
        """Flush pending counter and gauge writes to the store."""
        if self._store is None:
            return
        if not self._pending_writes and not self._pending_gauge_writes:
            return
        pending = self._pending_writes
        pending_gauges = self._pending_gauge_writes
        self._pending_writes = []
        self._pending_gauge_writes = []
        try:
            async with self._flush_lock:
                for metric, labels, delta in pending:
                    await self._store.increment(metric, labels, delta)
                for metric, value, labels in pending_gauges:
                    await self._store.set_gauge(metric, value, labels)
                await self._store.flush()
        except Exception as exc:
            logger.warning(
                "Metrics flush failed; re-buffering %d counter + %d gauge writes: %s",
                len(pending),
                len(pending_gauges),
                exc,
            )
            self._pending_writes.extend(pending)
            self._pending_gauge_writes.extend(pending_gauges)

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

    # ----- Portfolio state (gauges; 1-Hz throttled to the store) -----

    def update_portfolio_state(
        self,
        *,
        pnl: float,
        exposure: float,
        open_positions: int,
        peak_capital: float,
        total_value: float,
    ) -> None:
        """Push a snapshot of portfolio state to the gauges.

        Called by ``PortfolioOptimizationAgent._emit_portfolio_update``
        after every fill/portfolio update. In-memory values are
        updated synchronously (cheap, O(1)). Writes to the
        persistent store are throttled to ``_PORTFOLIO_FLUSH_THROTTLE_S``
        (1 Hz) per the plan's hot-loop constraint.

        Daily PnL is computed as ``current_pnl - baseline_pnl``,
        where the baseline resets at local-date rollover. The
        reset is automatic — no cron, no separate task.
        """
        today = date.today()
        if self._pnl_daily_reset_day != today:
            self._pnl_daily_reset_day = today
            self._pnl_daily_baseline = pnl
        self._pnl_daily = pnl - self._pnl_daily_baseline
        self._exposure_total = exposure
        self._open_positions = open_positions
        self._peak_capital = peak_capital
        if peak_capital > 0:
            self._drawdown_pct = max(0.0, (peak_capital - total_value) / peak_capital)
        else:
            self._drawdown_pct = 0.0

        # Throttle the durable write: Prometheus scrapes are typically
        # 15-30s apart, so 1 Hz is well within resolution and avoids
        # the 5+ writes/fill that the unthrottled path would produce.
        if self._store is None:
            return
        now = time.monotonic()
        if now - self._last_portfolio_flush_ts < _PORTFOLIO_FLUSH_THROTTLE_S:
            return
        self._last_portfolio_flush_ts = now
        self._pending_gauge_writes.extend(
            [
                ("trading_pnl_daily", self._pnl_daily, {}),
                ("trading_exposure_total", exposure, {}),
                ("trading_open_positions", float(open_positions), {}),
                ("trading_drawdown_pct", self._drawdown_pct, {}),
                ("trading_peak_capital", peak_capital, {}),
            ]
        )

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
            "pnl_daily": self._pnl_daily,
            "exposure_total": self._exposure_total,
            "open_positions": self._open_positions,
            "drawdown_pct": self._drawdown_pct,
            "peak_capital": self._peak_capital,
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
                "# HELP trading_pnl_daily Realized PnL since local midnight",
                "# TYPE trading_pnl_daily gauge",
                f"trading_pnl_daily {snapshot['pnl_daily']}",
                "",
                "# HELP trading_exposure_total Sum of |qty * price| across open positions",
                "# TYPE trading_exposure_total gauge",
                f"trading_exposure_total {snapshot['exposure_total']}",
                "",
                "# HELP trading_open_positions Count of positions with non-zero quantity",
                "# TYPE trading_open_positions gauge",
                f"trading_open_positions {snapshot['open_positions']}",
                "",
                "# HELP trading_drawdown_pct Current drawdown as fraction of peak capital",
                "# TYPE trading_drawdown_pct gauge",
                f"trading_drawdown_pct {snapshot['drawdown_pct']}",
                "",
                "# HELP trading_peak_capital All-time peak total value (capital + exposure)",
                "# TYPE trading_peak_capital gauge",
                f"trading_peak_capital {snapshot['peak_capital']}",
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
