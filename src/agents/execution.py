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


class ExecutionAgent(BaseAgent):
    def __init__(self, event_store=None, broker: Any = None):
        super().__init__("execution", event_store=event_store)
        self._open_orders: dict[str, OrderEvent] = {}
        self._filled_orders: dict[str, list[FillEvent]] = {}
        self._rejected_orders: dict[str, OrderEvent] = {}
        self._paper_trading = broker is None
        self._broker: Any = broker

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
        signal = event.data
        instrument = signal.get("instrument", "")
        direction = signal.get("direction")
        confidence = signal.get("confidence", 0.0)
        price = signal.get("price")
        if direction == "neutral" or confidence < 0.3:
            return
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
        self.logger.info("Order placed: %s %s %d @ %.2f", side.value, instrument, quantity, price or 0)

    async def _handle_risk_check(self, event: Event) -> None:
        if not event.data.get("passed", False):
            self.logger.warning("Risk check failed: %s", event.data.get("check_name"))

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
        self.logger.info("Execution Agent stopping")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "paper_trading": self._paper_trading,
            "open_orders": len(self._open_orders),
            "filled_orders": sum(len(v) for v in self._filled_orders.values()),
        })
        return base
