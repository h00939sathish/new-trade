import pytest

from src.execution.router import (
    LiveOrderGuard,
    OrderCommand,
    PaperBroker,
    TradingRouter,
)
from src.schemas.events import Exchange, OrderSide, OrderType, ProductType


@pytest.mark.asyncio
async def test_paper_order_fills_locally_and_updates_account_state():
    paper = PaperBroker(initial_cash=10_000.0)
    router = TradingRouter(paper_broker=paper)

    result = await router.place_order(
        OrderCommand(
            instrument="RELIANCE",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product=ProductType.MIS,
            price=100.0,
        ),
        mode="paper",
    )

    assert result.accepted is True
    assert result.mode == "paper"
    assert result.status == "filled"
    assert result.fill_price == 100.0
    assert paper.cash == 9_000.0
    assert paper.positions["RELIANCE"] == 10


@pytest.mark.asyncio
async def test_live_order_is_blocked_without_guard_approval():
    live = RecordingLiveBroker()
    router = TradingRouter(paper_broker=PaperBroker(), live_broker=live)

    result = await router.place_order(
        OrderCommand(
            instrument="INFY",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            product=ProductType.MIS,
        ),
        mode="live",
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.error == "live_orders_disabled"
    assert live.orders == []


@pytest.mark.asyncio
async def test_live_order_delegates_to_broker_when_guard_approves():
    live = RecordingLiveBroker()
    router = TradingRouter(
        paper_broker=PaperBroker(),
        live_broker=live,
        live_guard=LiveOrderGuard(allow_live_orders=True, acknowledgement="ENABLE_LIVE"),
    )
    command = OrderCommand(
        instrument="TCS",
        exchange=Exchange.NSE,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=2,
        product=ProductType.CNC,
        price=3500.0,
    )

    result = await router.place_order(command, mode="live", acknowledgement="ENABLE_LIVE")

    assert result.accepted is True
    assert result.mode == "live"
    assert result.status == "accepted"
    assert result.broker_order_id == "LIVE-1"
    assert live.orders == [command]


@pytest.mark.asyncio
async def test_paper_order_rejects_when_cash_is_insufficient():
    router = TradingRouter(paper_broker=PaperBroker(initial_cash=50.0))

    result = await router.place_order(
        OrderCommand(
            instrument="HDFCBANK",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=2,
            product=ProductType.MIS,
            price=100.0,
        ),
        mode="paper",
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.error == "insufficient_cash"


class RecordingLiveBroker:
    def __init__(self) -> None:
        self.orders: list[OrderCommand] = []

    async def place_order(self, command: OrderCommand) -> str:
        self.orders.append(command)
        return f"LIVE-{len(self.orders)}"
