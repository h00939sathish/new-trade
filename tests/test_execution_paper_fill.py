import pytest

from src.agents.execution import ExecutionAgent
from src.schemas.events import (
    Exchange,
    OrderEvent,
    OrderSide,
    OrderType,
    ProductType,
    TickEvent,
)


class _StubMarketIntel:
    def __init__(self, tick=None):
        self._tick = tick

    def get_latest_tick(self, instrument: str):
        return self._tick if self._tick and self._tick.instrument == instrument else None

    def get_latest_ohlcv(self, instrument: str, interval: str = "minute"):
        return None


class _StubSystem:
    def __init__(self, market_intel):
        self.market_intel = market_intel


@pytest.mark.asyncio
async def test_simulate_fill_uses_latest_tick_when_order_price_missing():
    agent = ExecutionAgent()
    await agent.start(run_background_loop=False)

    latest_tick = TickEvent.create(
        instrument="RELIANCE",
        exchange=Exchange.NSE,
        last_price=2500.0,
        producer="market_intel",
    )
    agent.system = _StubSystem(_StubMarketIntel(latest_tick))

    emitted = []

    async def mock_emit(event):
        emitted.append(event)

    agent.emit = mock_emit

    order = OrderEvent.create(
        instrument="RELIANCE",
        exchange=Exchange.NSE,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        product=ProductType.MIS,
        price=None,
        producer="execution",
    )
    agent._open_orders[order.event_id] = order

    await agent._simulate_fill(order)

    assert emitted
    assert emitted[0].data["fill_price"] > 0
    assert emitted[0].data["fill_price"] == pytest.approx(2501.25)

    await agent.stop()
