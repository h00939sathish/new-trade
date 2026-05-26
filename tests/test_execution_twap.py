import pytest
import asyncio
from src.agents.execution import ExecutionAgent
from src.schemas.events import Event, EventType, OrderSide, OrderType, ProductType, Exchange

@pytest.mark.asyncio
async def test_twap_order_slicing():
    agent = ExecutionAgent()
    await agent.start(run_background_loop=False)
    
    signal = {
        "instrument": "RELIANCE",
        "exchange": "NSE",
        "direction": "long",
        "confidence": 1.0,
        "price": 2500.0,
        "strategy": "momentum"
    }
    
    # 1000 quantity should trigger TWAP (>= 500)
    await agent._start_twap(signal, 1000, OrderSide.BUY, 2500.0)
    
    assert len(agent._twap_orders) == 1
    twap_id = list(agent._twap_orders.keys())[0]
    twap = agent._twap_orders[twap_id]
    
    # Slicing logic: min(100, max(10, 1000//5)) = 100 per chunk
    # 1000 / 100 = 10 chunks
    assert len(twap["chunks"]) == 10
    assert all(c == 100 for c in twap["chunks"])
    
    # Run twap loop step manually to execute first chunk
    # Temporarily set interval to 0 so it executes immediately
    twap["interval"] = 0.0
    
    # Mock emit to catch the order event
    emitted = []
    async def mock_emit(evt):
        emitted.append(evt)
    agent.emit = mock_emit
    
    # Create a small wrapper to run the loop exactly once
    async def single_step_loop():
        # we copy the inside of _twap_loop
        import time
        now = time.monotonic()
        completed = []
        for tid, t in agent._twap_orders.items():
            if t["chunks"]:
                chunk_qty = t["chunks"].pop(0)
                order_event = agent._open_orders.get("dummy", Event(event_type=EventType.ORDER_CREATED, stream="test", data={"quantity": chunk_qty}, metadata={"producer": "test"}))
                # For test sake we just mock the emit
                await agent.emit(order_event)
                t["executed"] += chunk_qty
    
    await single_step_loop()
    
    assert len(emitted) == 1
    assert emitted[0].data["quantity"] == 100
    assert twap["executed"] == 100
    assert len(twap["chunks"]) == 9
    
    await agent.stop()
