import asyncio

import pytest

from src.agents.execution import ExecutionAgent
from src.schemas.events import OrderSide


@pytest.fixture(autouse=True)
def _isolated_order_db(tmp_path, monkeypatch):
    db_path = tmp_path / "order_state.db"
    monkeypatch.setattr("src.agents.execution._ORDER_DB_PATH", db_path)
    yield db_path


class MockBroker:
    def __init__(self):
        self.orders = []

    async def place_order(
        self,
        tradingsymbol,
        exchange,
        side,
        order_type,
        quantity,
        product,
        price=None,
        trigger_price=None,
        tag=None,
        disclosed_quantity=None,
        variety=None,
        **kwargs,
    ):
        order = {
            "tradingsymbol": tradingsymbol,
            "quantity": quantity,
            "disclosed_quantity": disclosed_quantity,
            "tag": tag,
        }
        self.orders.append(order)
        return f"mock_{len(self.orders)}"

    async def get_orders(self):
        return []

    async def get_positions(self):
        return []


@pytest.mark.asyncio
async def test_twap_iceberg_execution():
    broker = MockBroker()
    agent = ExecutionAgent(broker=broker)
    await agent.start(run_background_loop=False)

    # Simulate a signal approval that should trigger TWAP with iceberg
    signal = {
        "instrument": "TATACHEM",
        "direction": "long",
        "confidence": 0.9,
        "price": 2500.0,
        "exchange": "NSE",
    }

    # Quantity 1500 triggers TWAP (>= 500) and Iceberg (>= 1000)
    # _start_twap chunking respects risk_max_order_value:
    # 50_000 / 2500 = 20 shares per chunk.
    # iceberg disclosed_qty = max(1, 20 // 10) = 2
    await agent._start_twap(
        signal, total_quantity=1500, side=OrderSide.BUY, price=2500.0, iceberg=True
    )

    # Force one execution of the twap loop (it runs every 30s by default)
    # We can just manually trigger the logic inside _twap_loop for testing, or run the loop for a bit
    # To test without waiting, let's override interval
    for twap in agent._twap_orders.values():
        twap["interval"] = 0.0

    # Let the loop run briefly
    await asyncio.sleep(5.1)

    # At least one chunk should have been sent to broker
    assert len(broker.orders) > 0
    first_order = broker.orders[0]

    assert first_order["tradingsymbol"] == "TATACHEM"
    assert first_order["quantity"] == 20
    assert first_order["disclosed_quantity"] == 2

    await agent.stop()
