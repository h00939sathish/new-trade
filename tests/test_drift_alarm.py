"""
Regression tests for FIX P1.4 — position-drift alarm.

Before P1.4, the ReconciliationAgent did nothing in paper mode. After
P1.4 it subscribes to FILL events and verifies that position_registry
and portfolio_opt agree on the position quantity. If they diverge, it
emits a SystemEvent.error so the alert agent can notify.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.reconciliation import ReconciliationAgent
from src.event_store.memory import InMemoryEventStore
from src.risk.position_registry import position_registry
from src.schemas.events import (
    Event,
    EventMetadata,
    EventType,
)


@pytest.fixture(autouse=True)
def reset_state():
    position_registry.reset()
    yield
    position_registry.reset()


def _fill_event(instrument, side, qty, price, product="mis"):
    return Event(
        event_type=EventType.FILL,
        stream=f"fill.{instrument}",
        data={
            "instrument": instrument,
            "side": side,
            "fill_quantity": qty,
            "fill_price": price,
            "product": product,
            "commission": 0.0,
        },
        metadata=EventMetadata(producer="execution"),
    )


@pytest.mark.asyncio
async def test_drift_alarm_fires_when_registry_and_portfolio_diverge():
    """If position_registry and portfolio_opt disagree on a position,
    ReconciliationAgent must emit a position_drift error event."""
    # Set up an agent with a fake system where portfolio_opt is out of sync
    store = InMemoryEventStore()
    await store.connect()
    agent = ReconciliationAgent(event_store=store)

    # Pretend position_registry has 10 of RELIANCE
    await position_registry.update_from_fill("RELIANCE", "buy", 10, 2500.0)
    assert position_registry.get_quantity("RELIANCE") == 10

    # Pretend portfolio_opt says 25 (divergent)
    fake_portfolio = MagicMock()
    fake_portfolio.get_position.return_value = {"quantity": 25, "avg_cost": 2500.0}
    fake_system = MagicMock()
    fake_system.portfolio_opt = fake_portfolio
    agent.system = fake_system

    # Capture emitted events
    emitted = []
    agent.emit = AsyncMock(side_effect=lambda e: emitted.append(e))

    # Fire a FILL event
    fill = _fill_event("RELIANCE", "buy", 0, 0.0)  # zero-qty filler
    await agent._check_drift(fill)

    # An error event should have been emitted
    error_events = [e for e in emitted if "position_drift" in str(e.data.get("error", ""))]
    assert len(error_events) == 1, f"Expected 1 position_drift event, got {len(error_events)}"
    assert "RELIANCE" in str(error_events[0].data.get("error", ""))
    assert "registry=10" in str(error_events[0].data.get("error", ""))


@pytest.mark.asyncio
async def test_drift_alarm_does_not_fire_when_in_sync():
    """If position_registry and portfolio_opt agree, no error event."""
    store = InMemoryEventStore()
    await store.connect()
    agent = ReconciliationAgent(event_store=store)

    # Set up consistent state
    await position_registry.update_from_fill("RELIANCE", "buy", 10, 2500.0)

    fake_portfolio = MagicMock()
    fake_portfolio.get_position.return_value = {"quantity": 10, "avg_cost": 2500.0}
    fake_system = MagicMock()
    fake_system.portfolio_opt = fake_portfolio
    agent.system = fake_system

    emitted = []
    agent.emit = AsyncMock(side_effect=lambda e: emitted.append(e))

    fill = _fill_event("RELIANCE", "buy", 0, 0.0)
    await agent._check_drift(fill)

    error_events = [e for e in emitted if "position_drift" in str(e.data.get("error", ""))]
    assert len(error_events) == 0, f"Expected 0 drift events, got {len(error_events)}"


@pytest.mark.asyncio
async def test_drift_alarm_handles_missing_portfolio_gracefully():
    """If portfolio_opt is not wired (e.g., in unit tests), the alarm
    should not crash and should not fire a false positive."""
    store = InMemoryEventStore()
    await store.connect()
    agent = ReconciliationAgent(event_store=store)

    await position_registry.update_from_fill("RELIANCE", "buy", 10, 2500.0)

    # No system ref at all
    emitted = []
    agent.emit = AsyncMock(side_effect=lambda e: emitted.append(e))

    fill = _fill_event("RELIANCE", "buy", 0, 0.0)
    await agent._check_drift(fill)  # should not raise

    error_events = [e for e in emitted if "position_drift" in str(e.data.get("error", ""))]
    assert len(error_events) == 0


@pytest.mark.asyncio
async def test_drift_alarm_skips_empty_instrument():
    """FILL events with no instrument should be skipped silently."""
    store = InMemoryEventStore()
    await store.connect()
    agent = ReconciliationAgent(event_store=store)

    emitted = []
    agent.emit = AsyncMock(side_effect=lambda e: emitted.append(e))

    fill = Event(
        event_type=EventType.FILL,
        stream="fill.",
        data={"instrument": "", "side": "buy", "fill_quantity": 10, "fill_price": 100.0},
        metadata=EventMetadata(producer="execution"),
    )
    await agent._check_drift(fill)

    error_events = [e for e in emitted if "position_drift" in str(e.data.get("error", ""))]
    assert len(error_events) == 0
