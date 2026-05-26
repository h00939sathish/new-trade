import asyncio
import pytest
from src.agents.execution import ExecutionAgent
from src.schemas.events import Event, EventType, OrderSide, Exchange

class MockBroker:
    def __init__(self):
        self.orders = []
        
    async def place_order(self, tradingsymbol, exchange, side, order_type, quantity, product, price=None, trigger_price=None, tag=None, disclosed_quantity=None):
        order = {
            "tradingsymbol": tradingsymbol,
            "quantity": quantity,
            "disclosed_quantity": disclosed_quantity,
            "tag": tag,
        }
        self.orders.append(order)
        return f"mock_{len(self.orders)}"

@pytest.mark.asyncio
async def test_twap_iceberg_execution():
    broker = MockBroker()
    agent = ExecutionAgent(broker=broker)
    await agent.start(run_background_loop=False)
    
    # Simulate a signal approval that should trigger TWAP with iceberg
    signal = {
        "instrument": "RELIANCE",
        "direction": "long",
        "confidence": 0.9,
        "price": 2500.0,
        "exchange": "NSE"
    }
    
    # Quantity 1500 triggers TWAP (>= 500) and Iceberg (>= 1000)
    # _start_twap chunking: max(10, 1500 // 5) = 300
    # chunk_size = min(100, 300) = 100
    # 15 chunks of 100
    # iceberg disclosed_qty = max(1, 100 // 10) = 10
    await agent._start_twap(signal, total_quantity=1500, side=OrderSide.BUY, price=2500.0, iceberg=True)
    
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
    
    assert first_order["tradingsymbol"] == "RELIANCE"
    assert first_order["quantity"] == 100
    assert first_order["disclosed_quantity"] == 10
    
    await agent.on_stop()
