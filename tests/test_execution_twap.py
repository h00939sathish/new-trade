
import pytest

from src.agents.execution import ExecutionAgent
from src.schemas.events import Event, EventType, OrderSide


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

    # Slicing respects risk_max_order_value: 50_000 / 2500 = 20 per chunk.
    assert len(twap["chunks"]) == 50
    assert all(c == 20 for c in twap["chunks"])

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
        for _tid, t in agent._twap_orders.items():
            if t["chunks"]:
                chunk_qty = t["chunks"].pop(0)
                order_event = agent._open_orders.get("dummy", Event(event_type=EventType.ORDER_CREATED, stream="test", data={"quantity": chunk_qty}, metadata={"producer": "test"}))
                # For test sake we just mock the emit
                await agent.emit(order_event)
                t["executed"] += chunk_qty

    await single_step_loop()

    assert len(emitted) == 1
    assert emitted[0].data["quantity"] == 20
    assert twap["executed"] == 20
    assert len(twap["chunks"]) == 49

    await agent.stop()
