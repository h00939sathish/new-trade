import asyncio
import json
import logging
import aiosqlite
import time
from pathlib import Path
from typing import Any
from src.monitoring.latency_tracer import tracer

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.schemas.events import (
    Event,
    EventType,
    Exchange,
    FillEvent,
    OrderEvent,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)

# Maximum seconds to wait for a risk check before auto-rejecting a pending signal
_RISK_CHECK_TIMEOUT_SECONDS = 2.0

_ORDER_DB_PATH = Path("state/order_state.db")

logger = logging.getLogger("execution")


async def _init_order_db(db_path: Path) -> aiosqlite.Connection:
    """Initialize SQLite database for persistent order state."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path), timeout=1.0)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            event_id TEXT PRIMARY KEY,
            instrument TEXT NOT NULL,
            exchange TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            broker_order_id TEXT,
            strategy TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data_json TEXT NOT NULL,
            signal_id TEXT
        )
    """)
    try:
        await conn.execute("ALTER TABLE orders ADD COLUMN signal_id TEXT")
        await conn.commit()
    except aiosqlite.OperationalError:
        pass
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            instrument TEXT NOT NULL,
            side TEXT NOT NULL,
            fill_price REAL NOT NULL,
            fill_quantity INTEGER NOT NULL,
            filled_at TEXT NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(event_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS twaps (
            twap_id TEXT PRIMARY KEY,
            instrument TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL,
            signal_json TEXT NOT NULL,
            chunks_json TEXT NOT NULL,
            executed INTEGER NOT NULL,
            total INTEGER NOT NULL,
            last_executed_at REAL NOT NULL,
            interval REAL NOT NULL,
            iceberg BOOLEAN NOT NULL
        )
    """)
    await conn.commit()
    return conn


class ExecutionAgent(BaseAgent):
    def __init__(self, event_store=None, broker: Any = None, order_db_path: Path | None = None):
        super().__init__("execution", event_store=event_store)
        self._open_orders: dict[str, OrderEvent] = {}
        self._pending_orders: dict[str, OrderEvent] = {}
        self._filled_orders: dict[str, list[FillEvent]] = {}
        self._rejected_orders: dict[str, OrderEvent] = {}
        self._paper_trading = broker is None
        self._broker: Any = broker
        # Signals waiting for risk approval, keyed by signal event_id
        self._pending_signals: dict[str, dict[str, Any]] = {}
        self._available_capital = 1_000_000.0
        self._order_strategies: dict[str, str] = {}
        # Order persistence
        self._order_db_path = order_db_path or _ORDER_DB_PATH
        self._order_db: aiosqlite.Connection | None = None
        self._twap_orders: dict[str, dict[str, Any]] = {}
        self._db_lock = None
        self._latest_depth: dict[str, dict] = {}
        self._broker_seen_fills: dict[str, int] = {}
        self._live_order_poll_interval = max(1.0, float(settings.broker_order_poll_interval_seconds))

    def _get_db_lock(self):
        if self._db_lock is None:
            self._db_lock = asyncio.Lock()
        return self._db_lock

    async def on_start(self) -> None:
        self.logger.info("Execution Agent initializing (paper=%s)", self._paper_trading)
        self.subscribe_signals()
        self.subscribe_risk()
        self.subscribe(EventType.PORTFOLIO_UPDATE)
        self.subscribe(EventType.TICK)
        # Initialize order persistence DB
        try:
            self._order_db = await _init_order_db(self._order_db_path)
            await self._load_outstanding_orders()
            await self._load_active_twaps()
        except Exception as e:
            self.logger.error("Failed to initialize order DB: %s", e)

        # Reconcile orders with broker on startup if not paper trading
        if not self._paper_trading and self._broker is not None:
            try:
                await self.reconcile_orders()
            except Exception as e:
                self.logger.error("Error during startup broker reconciliation: %s", e)

        task = asyncio.create_task(self._twap_loop(), name="execution.twap_loop")
        self._tasks.append(task)
        if not self._paper_trading and self._broker is not None:
            poll_task = asyncio.create_task(
                self._live_order_status_loop(),
                name="execution.live_order_status_loop",
            )
            self._tasks.append(poll_task)

    async def _load_outstanding_orders(self) -> None:
        """Load outstanding (non-terminal) orders from disk on restart."""
        if self._order_db is None:
            return
        async with self._order_db.execute(
            "SELECT event_id, data_json FROM orders WHERE status IN ('pending', 'accepted')"
        ) as cursor:
            count = 0
            async for row in cursor:
                try:
                    data = json.loads(row["data_json"])
                    order = OrderEvent(**data)
                    self._open_orders[row["event_id"]] = order
                    count += 1
                except Exception as e:
                    self.logger.warning("Failed to restore order %s: %s", row["event_id"], e)
            if count > 0:
                self.logger.warning(
                    "Restored %d outstanding orders from disk — verify with broker", count,
                )
                
            # If restart happens, we ensure orders map is populated properly
            # and triggers any reconciliation loops automatically via start methods


    async def _load_active_twaps(self) -> None:
        """Load active TWAP states from disk."""
        if self._order_db is None:
            return
        async with self._order_db.execute("SELECT * FROM twaps") as cursor:
            count = 0
            async for row in cursor:
                try:
                    twap_id = row["twap_id"]
                    self._twap_orders[twap_id] = {
                        "instrument": row["instrument"],
                        "side": OrderSide(row["side"]),
                        "price": row["price"],
                        "signal": json.loads(row["signal_json"]),
                        "chunks": json.loads(row["chunks_json"]),
                        "executed": row["executed"],
                        "total": row["total"],
                        "last_executed_at": row["last_executed_at"],
                        "interval": row["interval"],
                        "iceberg": bool(row["iceberg"]),
                    }
                    count += 1
                except Exception as e:
                    self.logger.warning("Failed to restore TWAP %s: %s", row["twap_id"], e)
            if count > 0:
                self.logger.warning("Restored %d active TWAPs from disk", count)

    async def _persist_order(self, order: OrderEvent, strategy: str = "unknown") -> None:
        """Write order state to disk."""
        if self._order_db is None:
            return
        async with self._get_db_lock():
            try:
                from datetime import UTC, datetime
                now = datetime.now(UTC).isoformat()
                await self._order_db.execute(
                    """INSERT OR REPLACE INTO orders
                   (event_id, instrument, exchange, side, order_type, quantity, price,
                    status, broker_order_id, strategy, created_at, updated_at, data_json, signal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order.event_id,
                        order.instrument,
                        order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange),
                        order.side.value if hasattr(order.side, "value") else str(order.side),
                        order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
                        order.quantity,
                        order.price,
                        order.data.get("status", "pending"),
                        order.data.get("broker_order_id"),
                        strategy or order.strategy,
                        now,
                        now,
                        json.dumps(order.model_dump(), default=str),
                        order.signal_id or order.data.get("signal_id"),
                    ),
                )
                await self._order_db.commit()
            except Exception as e:
                self.logger.error("Failed to persist order %s: %s", order.event_id, e)

    async def _update_order_status(self, event_id: str, status: str) -> None:
        """Update order status in persistent store."""
        if self._order_db is None:
            return
        async with self._get_db_lock():
            try:
                from datetime import UTC, datetime
                await self._order_db.execute(
                    "UPDATE orders SET status = ?, updated_at = ? WHERE event_id = ?",
                    (status, datetime.now(UTC).isoformat(), event_id),
                )
                await self._order_db.commit()
            except Exception as e:
                self.logger.error("Failed to update order status %s: %s", event_id, e)

    async def _persist_fill(self, fill: FillEvent) -> None:
        """Write fill to disk."""
        if self._order_db is None:
            return
        async with self._get_db_lock():
            try:
                from datetime import UTC, datetime
                await self._order_db.execute(
                    """INSERT OR IGNORE INTO fills
                   (fill_id, order_id, instrument, side, fill_price, fill_quantity, filled_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fill.event_id,
                        fill.data.get("order_id", ""),
                        fill.data.get("instrument", ""),
                        fill.data.get("side", ""),
                        fill.data.get("fill_price", 0),
                        fill.data.get("fill_quantity", 0),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                await self._order_db.commit()
                # Update corresponding order status
                order_id = fill.data.get("order_id", "")
                if order_id:
                    await self._order_db.execute(
                        "UPDATE orders SET status = ?, updated_at = ? WHERE event_id = ?",
                        ("filled", datetime.now(UTC).isoformat(), order_id)
                    )
                    await self._order_db.commit()
            except Exception as e:
                self.logger.error("Failed to persist fill %s: %s", fill.event_id, e)

    async def _persist_twap(self, twap_id: str) -> None:
        """Write TWAP state to disk."""
        if self._order_db is None:
            return
        twap = self._twap_orders.get(twap_id)
        if not twap:
            async with self._get_db_lock():
                await self._order_db.execute("DELETE FROM twaps WHERE twap_id = ?", (twap_id,))
                await self._order_db.commit()
            return
        async with self._get_db_lock():
            try:
                await self._order_db.execute(
                    """INSERT OR REPLACE INTO twaps
                    (twap_id, instrument, side, price, signal_json, chunks_json, executed, total, last_executed_at, interval, iceberg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        twap_id,
                        twap["instrument"],
                        twap["side"].value if hasattr(twap["side"], "value") else str(twap["side"]),
                        twap["price"],
                        json.dumps(twap["signal"], default=str),
                        json.dumps(twap["chunks"]),
                        twap["executed"],
                        twap["total"],
                        twap["last_executed_at"],
                        twap["interval"],
                        bool(twap.get("iceberg", False))
                    )
                )
                await self._order_db.commit()
            except Exception as e:
                self.logger.error("Failed to persist TWAP %s: %s", twap_id, e)

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.TICK:
                if "depth" in event.data and event.data["depth"]:
                    self._latest_depth[event.data["instrument"]] = event.data["depth"]
            case EventType.SIGNAL:
                await self._handle_signal(event)
            case EventType.RISK_CHECK:
                await self._handle_risk_check(event)
            case EventType.RISK_BREACH:
                self.logger.warning("Risk breach in execution: %s", event.data)
            case EventType.PORTFOLIO_UPDATE:
                self._available_capital = event.data.get("cash", self._available_capital)

    async def _handle_signal(self, event: Event) -> None:
        """Store the signal in a pending map and wait for risk approval.

        The order is NOT placed with the broker here (unless it is a neutral/exit signal).
        It is placed only when a matching RISK_CHECK event with passed=True is received.
        """
        start_time = time.monotonic()
        signal = event.data
        instrument = signal.get("instrument", "")
        direction = signal.get("direction")
        confidence = signal.get("confidence", 0.0)

        from src.risk.kill_switch import KillSwitch
        if KillSwitch().active and direction != "neutral":
            self.logger.warning("Signal blocked: Kill Switch is active (%s)", KillSwitch().reason)
            return

        # Handle position closing immediately (neutral signals bypass pre-trade risk checks)
        if direction == "neutral":
            qty = self._get_position_qty(instrument)
            if qty == 0:
                self.logger.info("Neutral signal received for %s, but no open position found.", instrument)
                return
            side = OrderSide.SELL if qty > 0 else OrderSide.BUY
            close_qty = abs(qty)

            order_event = OrderEvent.create(
                instrument=instrument,
                exchange=Exchange(signal.get("exchange", "NSE")),
                side=side,
                order_type=OrderType.MARKET,
                quantity=close_qty,
                product=ProductType(str(signal.get("product", "mis")).lower()),
                price=signal.get("price"),
                producer=self.name,
                status=OrderStatus.PENDING,
                signal_id=signal.get("event_id") or signal.get("_signal_event_id"),
                strategy=signal.get("strategy", "exit"),
                correlation_id=event.metadata.correlation_id,
            )
            self._order_strategies[order_event.event_id] = signal.get("strategy", "unknown")
            try:
                from src.monitoring.metrics import system_metrics
                system_metrics.count_order(order_event.status.value)
            except Exception:
                pass

            tag = order_event.event_id
            if self._broker is not None:
                existing_id = await self._is_order_placed(tag)
                if existing_id:
                    self.logger.warning("Duplicate exit order detected! Tag %s has order_id %s", tag, existing_id)
                    order_event.data["broker_order_id"] = existing_id
                    order_event.data["status"] = "accepted"
                    await self.emit(order_event)
                    self._open_orders[order_event.event_id] = order_event
                    if self._paper_trading:
                        await self._simulate_fill(order_event)
                    return

                exchange = Exchange(signal.get("exchange", "NSE"))
                broker_start = time.monotonic()
                broker_id = await self._broker.place_order(
                    tradingsymbol=instrument,
                    exchange=exchange,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=close_qty,
                    product=ProductType(str(signal.get("product", "mis")).lower()),
                    price=signal.get("price"),
                    tag=tag,
                )
                broker_rtt = (time.monotonic() - broker_start) * 1000
                tracer.record_trace(event.metadata.correlation_id, "broker_rtt", broker_rtt)
                order_event.data["broker_order_id"] = broker_id

            await self.emit(order_event)
            self._open_orders[order_event.event_id] = order_event
            await self._persist_order(order_event, strategy=signal.get("strategy", "exit"))
            if self._paper_trading:
                await self._simulate_fill(order_event)
                
            tracer.record_trace(event.metadata.correlation_id, "execution", (time.monotonic() - start_time) * 1000)
            return

        if confidence < 0.3:
            return

        # Store signal for later execution after risk approval
        self._pending_signals[event.event_id] = {
            "signal": signal,
            "received_at": time.monotonic(),
        }
        self.logger.info(
            "Signal PENDING risk approval: %s %s %.0f%% (id=%s)",
            instrument, direction, confidence * 100, event.event_id,
        )

        # Expire stale pending signals
        self._expire_stale_signals()

    async def _handle_risk_check(self, event: Event) -> None:
        """Process risk check results. If approved, execute the pending signal."""
        check_name = event.data.get("check_name", "")

        # Handle order_validation checks
        if check_name == "order_validation":
            if not passed:
                order_data = details.get("order", {})
                instrument = order_data.get("instrument", "unknown")
                self.logger.warning("Order REJECTED by risk manager: %s", instrument)
                return
            order_data = details.get("order", {})
            if order_data:
                import asyncio
                asyncio.create_task(self._submit_approved_order(order_data, correlation_id=event.metadata.correlation_id))
            return

        # Handle signal_validation checks
        if check_name != "signal_validation":
            if not passed:
                self.logger.warning("Risk check failed: %s", check_name)
            return

        passed = event.data.get("passed", False)
        details = event.data.get("details", {})
        signal_data = details.get("signal", {})
        signal_event_id = signal_data.get("_signal_event_id")

        if not signal_event_id:
            self.logger.warning("Risk check event missing _signal_event_id, dropping.")
            return

        # Try to find the matching pending signal
        pending = None
        if signal_event_id in self._pending_signals:
            pending = self._pending_signals.pop(signal_event_id)

        if not passed:
            instrument = signal_data.get("instrument", "unknown")
            self.logger.warning(
                "Signal REJECTED by risk manager: %s (check=%s)", instrument, check_name,
            )
            return

        if pending is None:
            # Risk check passed but no matching pending signal found
            self.logger.debug("Risk check passed but no matching pending signal found")
            return

        # Risk check PASSED — now execute the order
        await self._execute_approved_signal(pending["signal"], correlation_id=event.metadata.correlation_id)

    async def _execute_approved_signal(self, signal: dict[str, Any], correlation_id: str | None = None) -> None:
        """Create and execute an order for a risk-approved signal."""
        start_time = time.monotonic()
        from src.risk.kill_switch import KillSwitch
        if KillSwitch().active:
            self.logger.warning("Order blocked: Kill Switch is active (%s)", KillSwitch().reason)
            return

        instrument = signal.get("instrument", "")
        direction = signal.get("direction")
        confidence = signal.get("confidence", 0.0)
        price = signal.get("price")
        strategy_name = signal.get("strategy", "unknown")
        side = OrderSide.BUY if direction == "long" else OrderSide.SELL

        # Calculate quantity using features volatility if available (Bug 3.2)
        features = signal.get("features", {})
        volatility = features.get("atr") or features.get("std")
        if volatility is None:
            volatility = price * 0.02 if price else 2.0

        # Weight-aware capital allocation from the Institutional Portfolio Optimizer
        allocated_capital = self._available_capital
        system_ref = getattr(self, "system", None)
        if system_ref and hasattr(system_ref, "portfolio_opt"):
            strategy_weights = system_ref.portfolio_opt.get_strategy_weights()
            if strategy_weights and strategy_name in strategy_weights:
                weight = strategy_weights[strategy_name]
                allocated_capital = self._available_capital * weight
                self.logger.info(
                    "Strategy '%s' weight=%.1f%% → allocated capital=%.0f",
                    strategy_name, weight * 100, allocated_capital,
                )

        quantity = self._calculate_quantity(confidence, price, allocated_capital, volatility, strategy=strategy_name, instrument=instrument)
        if quantity <= 0:
            return

        # TWAP Smart Order Routing for large orders
        if quantity >= 500:
            is_iceberg = quantity >= 1000
            self.logger.info("Order quantity %d >= 500, routing to TWAP engine (iceberg=%s)", quantity, is_iceberg)
            await self._start_twap(
                instrument=instrument,
                side=side,
                total_quantity=quantity,
                price=price,
                signal=signal,
                iceberg=is_iceberg,
                correlation_id=correlation_id,
            )
            return

        order_event = OrderEvent.create(
            instrument=instrument,
            exchange=Exchange(signal.get("exchange", "NSE")),
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            product=ProductType(str(signal.get("product", "mis")).lower()),
            price=price,
            producer=self.name,
            signal_id=signal.get("event_id") or signal.get("_signal_event_id"),
            strategy=signal.get("strategy", "unknown"),
            correlation_id=correlation_id,
        )
        
        # Change order state to PROPOSED
        order_event.event_type = EventType.ORDER_PROPOSED
        order_event.status = OrderStatus.PROPOSED
        order_event.stream = f"order.proposed.{order_event.instrument}"
        order_event.data["status"] = OrderStatus.PROPOSED.value

        self._order_strategies[order_event.event_id] = signal.get("strategy", "unknown")

        tag = order_event.event_id
        if self._broker is not None:
            existing_id = await self._is_order_placed(tag)
            if existing_id:
                self.logger.warning("Duplicate entry order detected! Tag %s has order_id %s", tag, existing_id)
                return

        # Emit the proposed order to risk management
        await self.emit(order_event)
        self._pending_orders[order_event.event_id] = order_event
        self.logger.info("Order PROPOSED to Risk Management: %s %s %d @ %.2f", side.value, instrument, quantity, price or 0)
        tracer.record_trace(correlation_id, "execution_proposed", (time.monotonic() - start_time) * 1000)

    async def _submit_approved_order(self, order_data: dict[str, Any], correlation_id: str | None = None) -> None:
        """Submit an order that has passed order-level risk validation."""
        start_time = time.monotonic()
        event_id = order_data.get("event_id")
        if not event_id or event_id not in self._pending_orders:
            self.logger.warning("Approved order %s not found in pending orders", event_id)
            return
            
        order_event = self._pending_orders.pop(event_id)
        order_event.event_type = EventType.ORDER_CREATED
        order_event.status = OrderStatus.PENDING
        order_event.stream = f"order.created.{order_event.instrument}"
        order_event.data["status"] = OrderStatus.PENDING.value

        instrument = order_event.instrument
        quantity = order_event.quantity
        price = order_event.price
        side = order_event.side
        tag = order_event.event_id
        
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order(order_event.status.value)
        except Exception:
            pass

        if self._broker is not None:
            exchange = order_event.exchange
            variety = order_event.variety
            trigger_price = order_event.trigger_price
            
            # Upgrade MIS order to Cover Order if a trigger_price is provided (Native SL)
            if order_event.product.value == "mis" and trigger_price is not None and trigger_price > 0:
                variety = "co"
                order_event.variety = "co"
            
            broker_start = time.monotonic()
            try:
                broker_id = await self._broker.place_order(
                    tradingsymbol=instrument,
                    exchange=exchange,
                    side=side,
                    order_type=order_event.order_type,
                    quantity=quantity,
                    product=order_event.product,
                    price=price,
                    trigger_price=trigger_price,
                    variety=variety,
                    tag=tag,
                )
                broker_rtt = (time.monotonic() - broker_start) * 1000
                tracer.record_trace(correlation_id, "broker_rtt", broker_rtt)
                order_event.data["broker_order_id"] = broker_id
                self.logger.info("Broker order: %s (id=%s)", instrument, broker_id)
            except Exception as e:
                self.logger.error("Broker pre-submission reject: %s", e)
                order_event.status = OrderStatus.REJECTED
                order_event.data["status"] = OrderStatus.REJECTED.value
                order_event.data["reject_reason"] = str(e)
                await self._persist_order(order_event, strategy=self._order_strategies.get(order_event.event_id, "unknown"))
                raise e
            
        await self.emit(order_event)
        self._open_orders[order_event.event_id] = order_event
        await self._persist_order(order_event, strategy=self._order_strategies.get(order_event.event_id, "unknown"))
        self.logger.info(
            "Order APPROVED and placed: %s %s %d @ %.2f",
            side.value, instrument, quantity, price or 0,
        )
        if self._paper_trading:
            await self._simulate_fill(order_event)

        tracer.record_trace(correlation_id, "execution", (time.monotonic() - start_time) * 1000)

    def _expire_stale_signals(self) -> None:
        """Remove pending signals that have been waiting too long for risk approval."""
        now = time.monotonic()
        expired = [
            sid for sid, pdata in self._pending_signals.items()
            if now - pdata["received_at"] > _RISK_CHECK_TIMEOUT_SECONDS
        ]
        for sid in expired:
            pdata = self._pending_signals.pop(sid)
            instrument = pdata["signal"].get("instrument", "unknown")
            self.logger.warning(
                "Signal EXPIRED (no risk response in %.0fs): %s (id=%s)",
                _RISK_CHECK_TIMEOUT_SECONDS, instrument, sid,
            )

    async def _start_twap(
        self,
        signal: dict[str, Any],
        total_quantity: int,
        side: OrderSide,
        price: float | None,
        iceberg: bool = False,
        correlation_id: str | None = None,
        instrument: str | None = None,
    ) -> None:
        """Slice a large order into smaller chunks to execute over time (TWAP)."""
        if instrument is None:
            instrument = signal.get("instrument", "")
        # Slicing logic: max 100 per chunk, or at least 5 chunks
        chunk_size = min(100, max(10, total_quantity // 5))
        if price is not None and price > 0:
            max_value_chunk = max(1, int(settings.risk_max_order_value // price))
            chunk_size = min(chunk_size, max_value_chunk)
        chunks = []
        rem = total_quantity
        while rem > 0:
            qty = min(chunk_size, rem)
            chunks.append(qty)
            rem -= qty

        twap_id = f"twap_{instrument}_{time.time()}"
        self._twap_orders[twap_id] = {
            "instrument": instrument,
            "side": side,
            "price": price,
            "signal": signal,
            "chunks": chunks,
            "executed": 0,
            "total": total_quantity,
            "last_executed_at": 0.0,
            "interval": 30.0,  # Execute a chunk every 30 seconds
            "iceberg": iceberg,
            "retries": 0,
            "status": "active",
            "correlation_id": correlation_id,
        }
        await self._persist_twap(twap_id)
        self.logger.info("TWAP %s initialized: %d chunks of ~%d for %s (Iceberg=%s)", twap_id, len(chunks), chunk_size, instrument, iceberg)

    async def _twap_loop(self) -> None:
        """Background loop executing TWAP slices."""
        while self._running:
            try:
                now = time.monotonic()
                completed = []
                for twap_id, twap in self._twap_orders.items():
                    if twap.get("status") == "quarantined":
                        continue
                        
                    if not twap["chunks"]:
                        completed.append(twap_id)
                        continue

                    # Exponential backoff based on retries
                    retries = twap.get("retries", 0)
                    delay = twap["interval"] * (2 ** retries)
                    if now - twap["last_executed_at"] >= delay:
                        chunk_qty = twap["chunks"].pop(0)

                        # Generate the order slice
                        disclosed_qty = None
                        if twap.get("iceberg") and chunk_qty >= 10:
                            # Reveal only 10% of the chunk, minimum 1
                            disclosed_qty = max(1, chunk_qty // 10)

                        # Iceberg requires LIMIT orders in Indian markets usually, but we keep it MARKET or LIMIT if price exists
                        order_type = OrderType.LIMIT if twap["price"] else OrderType.MARKET

                        order_event = OrderEvent.create(
                            instrument=twap["instrument"],
                            exchange=Exchange(twap["signal"].get("exchange", "NSE")),
                            side=twap["side"],
                            order_type=order_type,
                            quantity=chunk_qty,
                            product=ProductType(str(twap["signal"].get("product", "mis")).lower()),
                            price=twap["price"],
                            disclosed_quantity=disclosed_qty,
                            producer=self.name,
                            signal_id=twap["signal"].get("event_id") or twap["signal"].get("_signal_event_id"),
                            strategy=twap["signal"].get("strategy", "unknown"),
                            correlation_id=twap.get("correlation_id"),
                        )
                        tag = order_event.event_id

                        if not await self._validate_order_before_submit(order_event):
                            twap["chunks"].insert(0, chunk_qty)
                            twap["status"] = "quarantined"
                            self.logger.critical(
                                "TWAP %s quarantined by pre-submit risk gate.",
                                twap_id,
                            )
                            await self._persist_twap(twap_id)
                            continue

                        if self._broker is not None:
                            try:
                                broker_start = time.monotonic()
                                trigger_price = order_event.trigger_price
                                variety = order_event.variety
                                if order_event.product.value == "mis" and trigger_price is not None and trigger_price > 0:
                                    variety = "co"
                                    order_event.variety = "co"
                                    
                                broker_id = await self._broker.place_order(
                                    tradingsymbol=twap["instrument"],
                                    exchange=order_event.exchange,
                                    side=order_event.side,
                                    order_type=order_event.order_type,
                                    quantity=chunk_qty,
                                    product=order_event.product,
                                    price=twap["price"],
                                    trigger_price=trigger_price,
                                    variety=variety,
                                    tag=tag,
                                    disclosed_quantity=disclosed_qty,
                                )
                                broker_rtt = (time.monotonic() - broker_start) * 1000
                                tracer.record_trace(twap.get("correlation_id"), "broker_rtt", broker_rtt)
                                order_event.data["broker_order_id"] = broker_id
                            except Exception as e:
                                self.logger.error("TWAP broker failure on chunk: %s", e)
                                twap["retries"] = twap.get("retries", 0) + 1
                                if twap["retries"] > 3:
                                    self.logger.critical("TWAP %s quarantined after 3 retries. Manual intervention required.", twap_id)
                                    twap["status"] = "quarantined"
                                    # Create incident event
                                    from src.schemas.events import EventType, Event, EventMetadata
                                    err_event = Event(
                                        event_type=EventType.SYSTEM_ERROR,
                                        stream="system.errors",
                                        data={"fatal": False, "reason": f"TWAP {twap_id} broker failure", "details": str(e)},
                                        metadata=EventMetadata(producer=self.name)
                                    )
                                    await self.emit(err_event)
                                else:
                                    twap["chunks"].insert(0, chunk_qty)
                                await self._persist_twap(twap_id)
                                continue

                        await self.emit(order_event)
                        self._open_orders[order_event.event_id] = order_event
                        await self._persist_order(order_event, strategy=twap["signal"].get("strategy", "unknown"))

                        twap["executed"] += chunk_qty
                        twap["last_executed_at"] = now
                        twap["retries"] = 0
                        await self._persist_twap(twap_id)
                        
                        self.logger.info(
                            "TWAP %s executed chunk %d/%d. Progress: %d/%d",
                            twap_id, chunk_qty, chunk_qty, twap["executed"], twap["total"]
                        )

                        if self._paper_trading:
                            await self._simulate_fill(order_event)

                        if not twap["chunks"]:
                            completed.append(twap_id)

                for twap_id in completed:
                    del self._twap_orders[twap_id]
                    await self._persist_twap(twap_id)
                    self.logger.info("TWAP %s completed fully", twap_id)

            except Exception as e:
                self.logger.error("TWAP loop error: %s", e, exc_info=True)

            await asyncio.sleep(5.0)

    async def place_order(
        self,
        instrument: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        product: ProductType = ProductType.MIS,
        price: float | None = None,
        trigger_price: float | None = None,
        exchange: Exchange = Exchange.NSE,
        strategy: str = "unknown",
    ) -> OrderEvent:
        order_event = OrderEvent.create(
            instrument=instrument,
            exchange=exchange,
            side=side,
            order_type=order_type,
            quantity=quantity,
            product=product,
            price=price,
            trigger_price=trigger_price,
            producer=self.name,
            status=OrderStatus.PENDING,
            strategy=strategy,
        )
        self._order_strategies[order_event.event_id] = strategy
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order(order_event.status.value)
        except Exception:
            pass

        if not await self._validate_order_before_submit(order_event):
            return order_event

        tag = order_event.event_id
        if self._broker is not None:
            existing_id = await self._is_order_placed(tag)
            if existing_id:
                self.logger.warning("Duplicate placed order detected! Tag %s has order_id %s", tag, existing_id)
                order_event.data["broker_order_id"] = existing_id
                order_event.data["status"] = "accepted"
                await self.emit(order_event)
                self._open_orders[order_event.event_id] = order_event
                if self._paper_trading:
                    await self._simulate_fill(order_event)
                return order_event
            
            variety = "regular"
            if product.value == "mis" and trigger_price is not None and trigger_price > 0:
                variety = "co"
                order_event.variety = "co"
                order_event.data["variety"] = "co"

            try:
                broker_id = await self._broker.place_order(
                    tradingsymbol=instrument,
                    exchange=exchange,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    product=product,
                    price=price,
                    trigger_price=trigger_price,
                    variety=variety,
                    tag=tag,
                )
                order_event.data["broker_order_id"] = broker_id
            except Exception as e:
                self.logger.error("Broker reject on place_order: %s", e)
                order_event.status = OrderStatus.REJECTED
                order_event.data["status"] = OrderStatus.REJECTED.value
                order_event.data["reject_reason"] = str(e)
                await self._persist_order(order_event, strategy=strategy)
                raise e
        await self.emit(order_event)
        self._open_orders[order_event.event_id] = order_event
        await self._persist_order(order_event, strategy=strategy)
        if self._paper_trading:
            await self._simulate_fill(order_event)
        return order_event

    def _order_risk_checks(self, order: OrderEvent) -> list[dict[str, Any]]:
        price = float(order.price) if order.price is not None else None
        notional = order.quantity * price if price is not None else None
        current_qty = self._get_position_qty(order.instrument)
        is_reducing = (
            (order.side == OrderSide.SELL and current_qty > 0)
            or (order.side == OrderSide.BUY and current_qty < 0)
        )

        checks: list[dict[str, Any]] = [
            {
                "name": "positive_quantity",
                "passed": order.quantity > 0,
                "details": {"quantity": order.quantity},
            },
        ]

        checks.append({
            "name": "price_available",
            "passed": is_reducing or self._paper_trading or price is not None,
            "details": {
                "price": price,
                "is_reducing": is_reducing,
                "paper_trading": self._paper_trading,
            },
        })

        if notional is not None:
            checks.append({
                "name": "max_order_value",
                "passed": is_reducing or notional <= settings.risk_max_order_value,
                "details": {"order_value": notional, "max": settings.risk_max_order_value},
            })
            checks.append({
                "name": "available_leverage",
                "passed": is_reducing or notional <= self._available_capital * settings.risk_max_leverage,
                "details": {
                    "order_value": notional,
                    "available_capital": self._available_capital,
                    "max_leverage": settings.risk_max_leverage,
                },
            })

        return checks

    async def _validate_order_before_submit(self, order: OrderEvent) -> bool:
        checks = self._order_risk_checks(order)
        failed = [check for check in checks if not check["passed"]]
        if not failed:
            return True

        reason = ", ".join(check["name"] for check in failed)
        order.status = OrderStatus.REJECTED
        order.event_type = EventType.ORDER_REJECTED
        order.stream = f"order.rejected.{order.instrument}"
        order.data["status"] = OrderStatus.REJECTED.value
        order.data["rejection_reason"] = reason
        order.data["risk_checks"] = checks
        self._rejected_orders[order.event_id] = order
        self.logger.warning(
            "Order REJECTED before broker submission: %s %s %d (%s)",
            order.side.value,
            order.instrument,
            order.quantity,
            reason,
        )
        await self.emit(order)
        await self._persist_order(order, strategy=order.strategy or "unknown")
        return False

    async def cancel_order(self, order_id: str) -> None:
        if order_id in self._open_orders:
            order = self._open_orders.pop(order_id)
            order.data["status"] = OrderStatus.CANCELLED.value
            broker_order_id = order.data.get("broker_order_id")
            if broker_order_id and self._broker is not None:
                try:
                    await self._broker.cancel_order(broker_order_id)
                except Exception as e:
                    self.logger.error("Failed to cancel order %s on broker: %s", broker_order_id, e)
            try:
                from src.monitoring.metrics import system_metrics
                system_metrics.count_order("cancelled")
            except Exception:
                pass
            await self.emit(order)
            await self._update_order_status(order_id, "cancelled")
            self.logger.info("Order cancelled: %s", order_id)

    def set_paper_trading(self, enabled: bool) -> None:
        self._paper_trading = enabled
        self.logger.info("Paper trading: %s", enabled)

    def _resolve_paper_fill_price(self, order: OrderEvent) -> float:
        if order.price is not None and order.price > 0:
            return float(order.price)

        system_ref = getattr(self, "system", None)
        market_intel = getattr(system_ref, "market_intel", None) if system_ref else None
        if market_intel is not None:
            latest_tick = market_intel.get_latest_tick(order.instrument)
            tick_price = getattr(latest_tick, "last_price", None)
            if tick_price is None and latest_tick is not None:
                tick_price = latest_tick.data.get("last_price")
            if tick_price is not None and tick_price > 0:
                self.logger.warning(
                    "Paper fill for %s missing order price; using latest tick %.2f",
                    order.instrument,
                    tick_price,
                )
                return float(tick_price)

            latest_bar = market_intel.get_latest_ohlcv(order.instrument, "minute")
            bar_close = getattr(latest_bar, "close", None)
            if bar_close is None and latest_bar is not None:
                bar_close = latest_bar.data.get("close")
            if bar_close is not None and bar_close > 0:
                self.logger.warning(
                    "Paper fill for %s missing order price; using latest minute close %.2f",
                    order.instrument,
                    bar_close,
                )
                return float(bar_close)

        self.logger.warning(
            "Paper fill for %s has no valid price source; defaulting to 0",
            order.instrument,
        )
        return 0.0

    async def _simulate_fill(self, order: OrderEvent) -> None:
        import asyncio
        import random
        price = self._resolve_paper_fill_price(order)

        from src.risk.costs import TransactionCostModel
        cost_model = TransactionCostModel()
        
        # Add realistic exchange latency delay (50-150ms depending on load)
        latency = random.uniform(0.05, 0.15)
        await asyncio.sleep(latency)
        
        depth = self._latest_depth.get(order.instrument)
        fill_price = cost_model.effective_fill_price_with_depth(
            order.side.value, price, order.quantity, depth
        )
        
        product = order.product.value if hasattr(order.product, "value") else order.product
        commission = cost_model.total_cost(order.side.value, order.quantity, fill_price, product=product)
        slippage_bps = abs(fill_price - price) / price * 10000 if price else 0.0

        fill_event = FillEvent.create(
            order_id=order.event_id,
            instrument=order.instrument,
            exchange=order.exchange,
            side=order.side,
            fill_price=fill_price,
            fill_quantity=order.quantity,
            signal_id=order.signal_id,
            strategy=order.strategy or self._order_strategies.get(order.event_id, "unknown"),
            broker_order_id=order.data.get("broker_order_id"),
            commission=commission,
            slippage_bps=slippage_bps,
        )
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order("filled")
        except Exception:
            pass
        await self.emit(fill_event)
        await self._persist_fill(fill_event)
        if order.event_id in self._open_orders:
            del self._open_orders[order.event_id]
        if order.event_id not in self._filled_orders:
            self._filled_orders[order.event_id] = []
        self._filled_orders[order.event_id].append(fill_event)
        self.logger.info(
            "Fill simulated: %s %d @ %.2f (base=%.2f)",
            order.instrument, order.quantity, fill_price, price,
        )

    def _calculate_quantity(
        self,
        confidence: float,
        price: float | None,
        available_capital: float,
        volatility: float,
        strategy: str = "unknown",
        instrument: str = "",
    ) -> int:
        if price is None or price <= 0 or available_capital <= 0 or volatility <= 0:
            return 0

        # Kelly-based or fixed position sizing (Phase 3 Task 2)
        if settings.risk_sizing_method == "kelly" and strategy != "unknown":
            try:
                from src.risk.kelly_sizing import KellySizer
                sizer = KellySizer()
                # Dynamically calculate the sizing multiplier from performance database
                sizing_factor = sizer.get_position_sizing_factor(strategy)
                if sizing_factor > 0:
                    # Quantity = (capital * sizing_factor) / price
                    raw_qty = (available_capital * sizing_factor) / price
                    max_qty = (available_capital * sizer.max_allocation_pct) / price
                    return max(1, int(min(raw_qty, max_qty)))
            except Exception as e:
                self.logger.error("Error using Kelly sizing: %s. Falling back to ATR sizing.", e)

        if settings.risk_sizing_method == "hrp":
            try:
                # Retrieve cached HRP weights or use default
                # To avoid running HRP on every tick, the PortfolioAgent or a background task
                # should compute it. For now, we fetch from a global cache or fallback
                # In this simple implementation, we assign a default 5% max if HRP isn't explicitly set
                # Ideally, we call hrp_allocator here with recent returns, but that is blocking.
                # Assuming the risk_mgmt or portfolio agent has published hrp_weights to a global state:
                from src.risk.position_registry import position_registry
                hrp_weight = getattr(position_registry, "hrp_weights", {}).get(instrument, 0.05)
                # Max weight is provided by HRP
                raw_qty = (available_capital * hrp_weight) / price
                return max(1, int(raw_qty))
            except Exception as e:
                self.logger.error("Error using HRP sizing: %s", e)

        # Risk per trade: 1% of capital
        risk_per_trade = available_capital * 0.01
        # ATR-based stop distance (2x ATR or volatility)
        stop_distance = volatility * 2.0
        if stop_distance <= 0:
            return 0
        # Position size = risk / stop distance
        raw_qty = risk_per_trade / stop_distance
        # Cap at max 5% of capital per position
        max_qty = (available_capital * 0.05) / price
        return max(1, int(min(raw_qty, max_qty)))

    def _get_position_qty(self, instrument: str) -> int:
        from src.risk.position_registry import position_registry
        return position_registry.get_quantity(instrument)

    async def _is_order_placed(self, tag: str) -> str | None:
        if self._broker is None:
            return None
        try:
            orders = await self._broker.get_orders()
            for o in orders:
                if o.get("tag") == tag:
                    return o.get("order_id")
        except Exception as e:
            self.logger.error("Failed to check duplicate orders: %s", e)
        return None

    async def reconcile_orders(self) -> None:
        """Startup reconciliation: compare local DB open orders vs broker actual status."""
        if self._paper_trading or self._broker is None:
            return
        self.logger.info("Starting broker reconciliation...")
        try:
            broker_orders = await self._broker.get_orders()
            broker_orders_by_id = {o.get("order_id"): o for o in broker_orders if o.get("order_id")}
            broker_orders_by_tag = {o.get("tag"): o for o in broker_orders if o.get("tag")}
            
            reconciled_count = 0
            for event_id, order in list(self._open_orders.items()):
                b_order = None
                broker_order_id = order.data.get("broker_order_id") or order.order_id
                if broker_order_id:
                    b_order = broker_orders_by_id.get(broker_order_id)
                if not b_order:
                    b_order = broker_orders_by_tag.get(event_id)
                    
                if b_order:
                    broker_status = b_order.get("status", "").upper()
                    if broker_status == "COMPLETE":
                        self.logger.warning(
                            "Reconciliation: Order %s was FILLED while offline. Emitting FillEvent.", event_id
                        )
                        self._open_orders.pop(event_id, None)
                        await self._update_order_status(event_id, OrderStatus.FILLED.value)
                        
                        fill_qty = int(b_order.get("filled_quantity", order.quantity))
                        avg_price = float(b_order.get("average_price", order.price or 0.0))
                        
                        fill_event = FillEvent.create(
                            order_id=event_id,
                            instrument=order.instrument,
                            exchange=order.exchange,
                            side=order.side,
                            fill_price=avg_price,
                            fill_quantity=fill_qty,
                            signal_id=order.signal_id,
                            strategy=order.strategy or self._order_strategies.get(event_id, "unknown"),
                            broker_order_id=broker_order_id,
                        )
                        await self.emit(fill_event)
                        await self._persist_fill(fill_event)
                        reconciled_count += 1
                        
                    elif broker_status in ("REJECTED", "CANCELLED", "FAILED"):
                        self.logger.warning(
                            "Reconciliation: Order %s was %s while offline. Updating local status.", event_id, broker_status
                        )
                        self._open_orders.pop(event_id, None)
                        await self._update_order_status(event_id, OrderStatus.CANCELLED.value)
                        reconciled_count += 1
                else:
                    self.logger.warning("Reconciliation: Outstanding local order %s not found on broker", event_id)
                    
            if reconciled_count > 0:
                self.logger.info("Successfully reconciled %d orders with broker", reconciled_count)
            else:
                self.logger.info("Broker reconciliation complete (0 discrepancies found)")
        except Exception as e:
            self.logger.error("Failed to perform broker reconciliation: %s", e)

    async def on_stop(self) -> None:
        # Log any signals that were still pending approval at shutdown
        if self._pending_signals:
            self.logger.warning(
                "Shutting down with %d pending signals unapproved",
                len(self._pending_signals),
            )
        self.logger.info("Execution Agent stopping: Cancelling open orders...")
        # 1. Cancel all open/pending orders
        if self._open_orders:
            self.logger.info("Cancelling %d open orders on shutdown...", len(self._open_orders))
            for order_id in list(self._open_orders.keys()):
                try:
                    await self.cancel_order(order_id)
                except Exception as e:
                    self.logger.error("Failed to cancel order %s on shutdown: %s", order_id, e)

        # 2. Close open positions (ProductType.MIS)
        system_ref = getattr(self, "system", None)
        if system_ref:
            portfolio_agent = getattr(system_ref, "portfolio_opt", None)
            if portfolio_agent:
                open_positions = {
                    inst: data for inst, data in portfolio_agent._positions.items()
                    if data.get("quantity", 0) != 0 and (
                        str(data.get("product", "mis")).lower() == "mis"
                        or (hasattr(data.get("product"), "value") and str(data.get("product").value).lower() == "mis")
                    )
                }
                if open_positions:
                    self.logger.warning("Graceful Shutdown: Closing %d open MIS positions...", len(open_positions))
                    for inst, data in open_positions.items():
                        qty = data.get("quantity", 0)
                        side = OrderSide.SELL if qty > 0 else OrderSide.BUY
                        self.logger.warning("Graceful Shutdown: Market closing position for %s (qty=%d, side=%s)", inst, qty, side.value)
                        try:
                            await self.place_order(
                                instrument=inst,
                                side=side,
                                order_type=OrderType.MARKET,
                                quantity=abs(qty),
                                product=ProductType.MIS,
                            )
                        except Exception as e:
                            self.logger.error("Graceful Shutdown: Failed to place close order for %s: %s", inst, e)

                    # Wait for fill confirmations (with a 5-second timeout)
                    for _ in range(50):
                        if all(p.get("quantity", 0) == 0 for p in portfolio_agent._positions.values()):
                            self.logger.info("Graceful Shutdown: All positions closed successfully.")
                            break
                        await asyncio.sleep(0.1)
                    else:
                        self.logger.warning("Graceful Shutdown: Timeout waiting for position close confirmations.")
        if self._order_db is not None:
            await self._order_db.close()
            self._order_db = None
        self.logger.info("Execution Agent stopped")

    async def _live_order_status_loop(self) -> None:
        """Periodically poll live order status from the broker and handle fills."""
        self.logger.info("Starting live order status loop")
        while self._running:
            try:
                if self._broker is not None:
                    # Retrieve all orders from the broker for today
                    orders = await self._broker.get_orders()
                    for order in orders:
                        broker_order_id = order.get("order_id")
                        status = order.get("status")
                        
                        # Find the matching order event from self._open_orders
                        matching_order = None
                        for o_id, o_event in list(self._open_orders.items()):
                            if o_event.data.get("broker_order_id") == broker_order_id:
                                matching_order = o_event
                                break
                        
                        if matching_order:
                            if status in ("COMPLETE", "FILLED"):
                                # Emit a fill event!
                                fill_price = float(order.get("average_price", 0.0) or order.get("price", 0.0))
                                fill_qty = int(order.get("filled_quantity", matching_order.quantity))
                                
                                fill_event = FillEvent.create(
                                    order_id=matching_order.event_id,
                                    instrument=matching_order.instrument,
                                    exchange=matching_order.exchange,
                                    side=matching_order.side,
                                    fill_price=fill_price,
                                    fill_quantity=fill_qty,
                                    signal_id=matching_order.signal_id,
                                    strategy=matching_order.strategy or self._order_strategies.get(matching_order.event_id, "unknown"),
                                    broker_order_id=broker_order_id,
                                )
                                self.logger.info("Live order status loop detected FILL: %s %d @ %.2f", matching_order.instrument, fill_qty, fill_price)
                                await self.emit(fill_event)
                                await self._persist_fill(fill_event)
                                
                                # Update order event status to complete
                                matching_order.data["status"] = "filled"
                                matching_order.data["fill_price"] = fill_price
                                matching_order.data["filled_quantity"] = fill_qty
                                await self._persist_order(matching_order, strategy=matching_order.strategy or "unknown")
                                
                                if matching_order.event_id in self._open_orders:
                                    del self._open_orders[matching_order.event_id]
                            elif status in ("REJECTED", "CANCELLED", "FAILED"):
                                self.logger.warning("Live order status loop detected terminal failure: %s for %s", status, matching_order.instrument)
                                matching_order.data["status"] = status.lower()
                                matching_order.data["rejection_reason"] = order.get("status_message", "Cancelled or rejected by broker")
                                await self._persist_order(matching_order, strategy=matching_order.strategy or "unknown")
                                if matching_order.event_id in self._open_orders:
                                    del self._open_orders[matching_order.event_id]
            except Exception as e:
                self.logger.error("Error in live order status loop: %s", e, exc_info=True)
            await asyncio.sleep(2.0)

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "paper_trading": self._paper_trading,
            "open_orders": len(self._open_orders),
            "filled_orders": sum(len(v) for v in self._filled_orders.values()),
            "pending_signals": len(self._pending_signals),
        })
        return base
