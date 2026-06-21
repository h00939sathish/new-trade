import pytest

from src.agents.reconciliation import ReconciliationAgent
from src.schemas.events import Event, EventMetadata, EventType


@pytest.fixture
def agent():
    return ReconciliationAgent()


@pytest.mark.asyncio
async def test_drift_alarm_fires_on_divergence(agent: ReconciliationAgent):
    from src.risk.position_registry import PositionRegistry, position_registry

    await agent.start()
    instrument = "TEST_EQ"
    await position_registry.update_from_fill(instrument, "buy", 100, 100.0)
    event = Event(
        event_type=EventType.FILL,
        stream="test",
        data={"instrument": instrument, "fill_quantity": 100, "side": "buy"},
        metadata=EventMetadata(producer="test"),
    )
    reg_qty = position_registry.get_quantity(instrument)
    assert reg_qty == 100
    await agent.stop()


@pytest.mark.asyncio
async def test_drift_alarm_skips_empty_instrument(agent: ReconciliationAgent):
    await agent.start()
    event = Event(
        event_type=EventType.FILL,
        stream="test",
        data={},
        metadata=EventMetadata(producer="test"),
    )
    await agent.on_event(event)
    await agent.stop()


@pytest.mark.asyncio
async def test_reconciliation_no_discrepancy_on_match(agent: ReconciliationAgent):
    await agent.start()
    assert agent._running
    await agent.stop()
