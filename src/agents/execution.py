import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
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

_ORDER_DB_PATH = Path("order_state.db")

logger = logging.getLogger("execution")


def _init_order_db(db_path: Path) -> sqlite3.Connection:
    """Initialize SQLite database for persistent order state."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
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
            data_json TEXT NOT NULL
        )
    """)
    conn.execute("""
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
    conn.commit()
    return conn


class ExecutionAgent(BaseAgent):
    def __init__(self, event_store=None, broker: Any = None, order_db_path: Path | None = None):
        super().__init__("execution", event_store=event_store)
        self._open_orders: dict[str, OrderEvent] = {}
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
        self._order_db: sqlite3.Connection | None = None
        self._twap_orders: dict[str, dict[str, Any]] = {}

    async def on_start(self) -> None:
        self.logger.info("Execution Agent initializing (paper=%s)", self._paper_trading)
        self.subscribe_signals()
        self.subscribe_risk()
        self.subscribe(EventType.PORTFOLIO_UPDATE)
        # Initialize order persistence DB
        try:
            self._order_db = _init_order_db(self._order_db_path)
            self._load_outstanding_orders()
        except Exception as e:
            self.logger.error("Failed to initialize order DB: %s", e)
            
        task = asyncio.create_task(self._twap_loop(), name="execution.twap_loop")
        self._tasks.append(task)

    def _load_outstanding_orders(self) -> None:
        """Load outstanding (non-terminal) orders from disk on restart."""
        if self._order_db is None:
            return
        cursor = self._order_db.execute(
            "SELECT event_id, data_json FROM orders WHERE status IN ('pending', 'accepted')"
        )
        count = 0
        for row in cursor.fetchall():
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

    def _persist_order(self, order: OrderEvent, strategy: str = "unknown") -> None:
        """Write order state to disk."""
        if self._order_db is None:
            return
        try:
            from datetime import datetime, UTC
            now = datetime.now(UTC).isoformat()
            self._order_db.execute(
                """INSERT OR REPLACE INTO orders
                   (event_id, instrument, exchange, side, order_type, quantity, price,
                    status, broker_order_id, strategy, created_at, updated_at, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    strategy,
                    now,
                    now,
                    json.dumps(order.model_dump(), default=str),
                ),
            )
            self._order_db.commit()
        except Exception as e:
            self.logger.error("Failed to persist order %s: %s", order.event_id, e)

    def _update_order_status(self, event_id: str, status: str) -> None:
        """Update order status in persistent store."""
        if self._order_db is None:
            return
        try:
            from datetime import datetime, UTC
            self._order_db.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE event_id = ?",
                (status, datetime.now(UTC).isoformat(), event_id),
            )
            self._order_db.commit()
        except Exception as e:
            self.logger.error("Failed to update order status %s: %s", event_id, e)

    def _persist_fill(self, fill: FillEvent) -> None:
        """Write fill to disk."""
        if self._order_db is None:
            return
        try:
            from datetime import datetime, UTC
            self._order_db.execute(
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
            self._order_db.commit()
            # Update corresponding order status
            order_id = fill.data.get("order_id", "")
            if order_id:
                self._update_order_status(order_id, "filled")
        except Exception as e:
            self.logger.error("Failed to persist fill %s: %s", fill.event_id, e)

    async def on_event(self, event: Event) -> None:
        match event.event_type:
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
                product=ProductType.MIS,
                price=signal.get("price"),
                producer=self.name,
                status=OrderStatus.PENDING,
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
                broker_id = await self._broker.place_order(
                    tradingsymbol=instrument,
                    exchange=exchange,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=close_qty,
                    product=ProductType.MIS,
                    price=signal.get("price"),
                    tag=tag,
                )
                order_event.data["broker_order_id"] = broker_id
                
            await self.emit(order_event)
            self._open_orders[order_event.event_id] = order_event
            self._persist_order(order_event, strategy=signal.get("strategy", "exit"))
            if self._paper_trading:
                await self._simulate_fill(order_event)
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

        # Only process signal_validation checks (not order_validation)
        if check_name != "signal_validation":
            if not event.data.get("passed", False):
                self.logger.warning("Risk check failed: %s", check_name)
            return

        passed = event.data.get("passed", False)
        details = event.data.get("details", {})
        signal_data = details.get("signal", {})
        signal_event_id = signal_data.get("_signal_event_id")

        # Try to find the matching pending signal
        pending = None
        if signal_event_id and signal_event_id in self._pending_signals:
            pending = self._pending_signals.pop(signal_event_id)
        else:
            # Fallback: match by instrument + direction from signal data
            instrument = signal_data.get("instrument", "")
            direction = signal_data.get("direction", "")
            for sid, pdata in list(self._pending_signals.items()):
                psig = pdata["signal"]
                if psig.get("instrument") == instrument and psig.get("direction") == direction:
                    pending = self._pending_signals.pop(sid)
                    break

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
        await self._execute_approved_signal(pending["signal"])

    async def _execute_approved_signal(self, signal: dict[str, Any]) -> None:
        """Create and execute an order for a risk-approved signal."""
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

        quantity = self._calculate_quantity(confidence, price, allocated_capital, volatility)
        if quantity <= 0:
            return
            
        # TWAP Smart Order Routing for large orders
        if quantity >= 500:
            iceberg = quantity >= 1000
            self.logger.info("Order quantity %d >= 500, routing to TWAP engine (iceberg=%s)", quantity, iceberg)
            await self._start_twap(signal, quantity, side, price, iceberg=iceberg)
            return
            
        order_event = OrderEvent.create(
            instrument=instrument,
            exchange=Exchange(signal.get("exchange", "NSE")),
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            product=ProductType.MIS,
            price=price,
            producer=self.name,
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
                self.logger.warning("Duplicate entry order detected! Tag %s has order_id %s", tag, existing_id)
                order_event.data["broker_order_id"] = existing_id
                order_event.data["status"] = "accepted"
                await self.emit(order_event)
                self._open_orders[order_event.event_id] = order_event
                if self._paper_trading:
                    await self._simulate_fill(order_event)
                return

            exchange = Exchange(signal.get("exchange", "NSE"))
            broker_id = await self._broker.place_order(
                tradingsymbol=instrument,
                exchange=exchange,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                product=ProductType.MIS,
                price=price,
                tag=tag,
            )
            order_event.data["broker_order_id"] = broker_id
            self.logger.info("Broker order: %s (id=%s)", instrument, broker_id)
        await self.emit(order_event)
        self._open_orders[order_event.event_id] = order_event
        self._persist_order(order_event, strategy=signal.get("strategy", "unknown"))
        self.logger.info(
            "Order APPROVED and placed: %s %s %d @ %.2f",
            side.value, instrument, quantity, price or 0,
        )
        if self._paper_trading:
            await self._simulate_fill(order_event)

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

    async def _start_twap(self, signal: dict[str, Any], total_quantity: int, side: OrderSide, price: float | None, iceberg: bool = False) -> None:
        """Slice a large order into smaller chunks to execute over time (TWAP)."""
        instrument = signal.get("instrument", "")
        # Slicing logic: max 100 per chunk, or at least 5 chunks
        chunk_size = min(100, max(10, total_quantity // 5))
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
        }
        self.logger.info("TWAP %s initialized: %d chunks of ~%d for %s (Iceberg=%s)", twap_id, len(chunks), chunk_size, instrument, iceberg)

    async def _twap_loop(self) -> None:
        """Background loop executing TWAP slices."""
        while self._running:
            try:
                now = time.monotonic()
                completed = []
                for twap_id, twap in self._twap_orders.items():
                    if not twap["chunks"]:
                        completed.append(twap_id)
                        continue
                        
                    if now - twap["last_executed_at"] >= twap["interval"]:
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
                            product=ProductType.MIS,
                            price=twap["price"],
                            disclosed_quantity=disclosed_qty,
                            producer=self.name,
                        )
                        tag = order_event.event_id
                        
                        if self._broker is not None:
                            try:
                                broker_id = await self._broker.place_order(
                                    tradingsymbol=twap["instrument"],
                                    exchange=order_event.exchange,
                                    side=order_event.side,
                                    order_type=order_event.order_type,
                                    quantity=chunk_qty,
                                    product=ProductType.MIS,
                                    price=twap["price"],
                                    tag=tag,
                                    disclosed_quantity=disclosed_qty,
                                )
                                order_event.data["broker_order_id"] = broker_id
                            except Exception as e:
                                self.logger.error("TWAP broker failure on chunk: %s", e)
                                # Re-insert the chunk to try again
                                twap["chunks"].insert(0, chunk_qty)
                                continue
                                
                        await self.emit(order_event)
                        self._open_orders[order_event.event_id] = order_event
                        self._persist_order(order_event, strategy=twap["signal"].get("strategy", "unknown"))
                        
                        twap["executed"] += chunk_qty
                        twap["last_executed_at"] = now
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
        )
        self._order_strategies[order_event.event_id] = strategy
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order(order_event.status.value)
        except Exception:
            pass

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

            broker_id = await self._broker.place_order(
                tradingsymbol=instrument,
                exchange=exchange,
                side=side,
                order_type=order_type,
                quantity=quantity,
                product=product,
                price=price,
                trigger_price=trigger_price,
                tag=tag,
            )
            order_event.data["broker_order_id"] = broker_id
        await self.emit(order_event)
        self._open_orders[order_event.event_id] = order_event
        if self._paper_trading:
            await self._simulate_fill(order_event)
        return order_event

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
            self._update_order_status(order_id, "cancelled")
            self.logger.info("Order cancelled: %s", order_id)

    def set_paper_trading(self, enabled: bool) -> None:
        self._paper_trading = enabled
        self.logger.info("Paper trading: %s", enabled)

    async def _simulate_fill(self, order: OrderEvent) -> None:
        import asyncio
        price = order.price
        if price is None or price <= 0:
            self.logger.warning(
                "Paper fill for %s has no valid price — using last known tick price or 0",
                order.instrument,
            )
            price = 0.0
        
        from src.risk.costs import TransactionCostModel
        cost_model = TransactionCostModel()
        fill_price = cost_model.effective_fill_price(order.side.value, price)
        
        fill_event = FillEvent.create(
            order_id=order.event_id,
            instrument=order.instrument,
            exchange=order.exchange,
            side=order.side,
            fill_price=fill_price,
            fill_quantity=order.quantity,
        )
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order("filled")
        except Exception:
            pass
        await asyncio.sleep(0.1)
        await self.emit(fill_event)
        self._persist_fill(fill_event)
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
        self, confidence: float, price: float | None, available_capital: float, volatility: float
    ) -> int:
        if price is None or price <= 0 or available_capital <= 0 or volatility <= 0:
            return 0
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
                open_positions = {inst: data for inst, data in portfolio_agent._positions.items() if data.get("quantity", 0) != 0}
                if open_positions:
                    self.logger.warning("Graceful Shutdown: Closing %d open positions...", len(open_positions))
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
        self.logger.info("Execution Agent stopped")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "paper_trading": self._paper_trading,
            "open_orders": len(self._open_orders),
            "filled_orders": sum(len(v) for v in self._filled_orders.values()),
            "pending_signals": len(self._pending_signals),
        })
        return base

