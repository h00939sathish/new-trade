import time
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
_RISK_CHECK_TIMEOUT_SECONDS = 10.0


class ExecutionAgent(BaseAgent):
    def __init__(self, event_store=None, broker: Any = None):
        super().__init__("execution", event_store=event_store)
        self._open_orders: dict[str, OrderEvent] = {}
        self._filled_orders: dict[str, list[FillEvent]] = {}
        self._rejected_orders: dict[str, OrderEvent] = {}
        self._paper_trading = broker is None
        self._broker: Any = broker
        # Signals waiting for risk approval, keyed by signal event_id
        self._pending_signals: dict[str, dict[str, Any]] = {}

    async def on_start(self) -> None:
        self.logger.info("Execution Agent initializing (paper=%s)", self._paper_trading)
        self.subscribe_signals()
        self.subscribe_risk()

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.SIGNAL:
                await self._handle_signal(event)
            case EventType.RISK_CHECK:
                await self._handle_risk_check(event)
            case EventType.RISK_BREACH:
                self.logger.warning("Risk breach in execution: %s", event.data)

    async def _handle_signal(self, event: Event) -> None:
        """Store the signal in a pending map and wait for risk approval.

        The order is NOT placed with the broker here. It is placed only
        when a matching RISK_CHECK event with passed=True is received.
        """
        signal = event.data
        instrument = signal.get("instrument", "")
        direction = signal.get("direction")
        confidence = signal.get("confidence", 0.0)
        if direction == "neutral" or confidence < 0.3:
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
        instrument = signal.get("instrument", "")
        direction = signal.get("direction")
        confidence = signal.get("confidence", 0.0)
        price = signal.get("price")
        side = OrderSide.BUY if direction == "long" else OrderSide.SELL
        quantity = self._calculate_quantity(confidence, price)
        if quantity <= 0:
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
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order(order_event.status.value)
        except Exception:
            pass
        if self._broker is not None:
            exchange = Exchange(signal.get("exchange", "NSE"))
            broker_id = await self._broker.place_order(
                tradingsymbol=instrument,
                exchange=exchange,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                product=ProductType.MIS,
                price=price,
            )
            order_event.data["broker_order_id"] = broker_id
            self.logger.info("Broker order: %s (id=%s)", instrument, broker_id)
        await self.emit(order_event)
        self._open_orders[order_event.event_id] = order_event
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
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order(order_event.status.value)
        except Exception:
            pass
        if self._broker is not None:
            broker_id = await self._broker.place_order(
                tradingsymbol=instrument,
                exchange=exchange,
                side=side,
                order_type=order_type,
                quantity=quantity,
                product=product,
                price=price,
                trigger_price=trigger_price,
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
            try:
                from src.monitoring.metrics import system_metrics
                system_metrics.count_order("cancelled")
            except Exception:
                pass
            await self.emit(order)
            self.logger.info("Order cancelled: %s", order_id)

    def set_paper_trading(self, enabled: bool) -> None:
        self._paper_trading = enabled
        self.logger.info("Paper trading: %s", enabled)

    async def _simulate_fill(self, order: OrderEvent) -> None:
        import asyncio
        price = order.price or 100.0
        fill_event = FillEvent.create(
            order_id=order.event_id,
            instrument=order.instrument,
            exchange=order.exchange,
            side=order.side,
            fill_price=price,
            fill_quantity=order.quantity,
        )
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_order("filled")
        except Exception:
            pass
        await asyncio.sleep(0.1)
        await self.emit(fill_event)
        if order.event_id in self._open_orders:
            del self._open_orders[order.event_id]
        if order.event_id not in self._filled_orders:
            self._filled_orders[order.event_id] = []
        self._filled_orders[order.event_id].append(fill_event)
        self.logger.info(
            "Fill simulated: %s %d @ %.2f",
            order.instrument, order.quantity, price,
        )

    def _calculate_quantity(self, confidence: float, price: float | None = None) -> int:
        base = int(confidence * 100)
        return max(base, 1)

    async def on_stop(self) -> None:
        # Log any signals that were still pending approval at shutdown
        if self._pending_signals:
            self.logger.warning(
                "Shutting down with %d pending signals unapproved",
                len(self._pending_signals),
            )
        self.logger.info("Execution Agent stopping")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "paper_trading": self._paper_trading,
            "open_orders": len(self._open_orders),
            "filled_orders": sum(len(v) for v in self._filled_orders.values()),
            "pending_signals": len(self._pending_signals),
        })
        return base

