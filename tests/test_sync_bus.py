"""
Regression tests for FIX S2.1 — SyncEventBus event ordering.

Before this fix, when strategy_gen emitted a SIGNAL, the SyncEventBus
would call risk_mgmt.on_event(SIGNAL) which synchronously emitted a
RISK_CHECK. The bus would then route the RISK_CHECK to execution BEFORE
the original SIGNAL — because the bus was iterating subscribers in
order. Execution's _pending_signals was empty when the risk check
arrived, so every order was silently dropped.

The fix defers nested events: when publish() is called recursively
during another publish, the new event is queued and delivered only
after the outer subscriber chain completes.

These tests verify the ordering guarantee directly without spinning up
the full system.
"""
import asyncio
import pytest
from dataclasses import dataclass, field

from src.schemas.events import Event, EventMetadata, EventType
from src.backtest.sync_bus import SyncEventBus


# Minimal mock agent that records the order of events it receives and
# can emit a nested event when it processes its first event.
@dataclass
class MockAgent:
    name: str
    received: list[EventType] = field(default_factory=list)
    nested_event_to_emit: Event | None = None
    _bus: SyncEventBus | None = None

    def get_subscribed_event_types(self) -> set[EventType]:
        # Required attribute for SyncEventBus.register_agent
        return getattr(self, "_subscribed", set())

    async def on_event(self, event: Event) -> None:
        self.received.append(event.event_type)
        if self.nested_event_to_emit and event.event_type == EventType.SIGNAL:
            # Simulate risk_mgmt emitting a nested RISK_CHECK while
            # processing a SIGNAL
            await self._bus.publish(self.nested_event_to_emit)


def _register(bus: SyncEventBus, agent: MockAgent, types: set[EventType]) -> None:
    """Register a mock agent with explicit event-type subscriptions."""
    agent._subscribed = types
    for et in types:
        etype_str = et.value if hasattr(et, "value") else str(et)
        bus._subscribers.setdefault(etype_str, []).append(agent)


@pytest.fixture
def setup():
    bus = SyncEventBus()
    return bus


def _make_event(event_type: EventType, producer: str, correlation_id: str = "test"):
    return Event(
        event_type=event_type,
        stream=event_type.value,
        data={"_signal_event_id": "sig-1"},
        metadata=EventMetadata(producer=producer, correlation_id=correlation_id),
    )


@pytest.mark.asyncio
async def test_parent_event_delivered_to_all_subscribers_before_nested():
    """When agent A processes SIGNAL and emits nested RISK_CHECK, agent B
    (subscribed to both SIGNAL and RISK_CHECK) should see SIGNAL first."""
    bus = SyncEventBus()

    # Execution agent subscribes to both SIGNAL and RISK_CHECK
    execution = MockAgent(name="execution")
    _register(bus, execution, {EventType.SIGNAL, EventType.RISK_CHECK})

    # Risk agent subscribes to SIGNAL only; emits nested RISK_CHECK
    risk = MockAgent(name="risk_mgmt")
    risk.nested_event_to_emit = _make_event(EventType.RISK_CHECK, producer="risk_mgmt")
    risk._bus = bus
    _register(bus, risk, {EventType.SIGNAL})

    # Fire a SIGNAL — produced by strategy_gen, not in the agent list
    signal = _make_event(EventType.SIGNAL, producer="strategy_gen")
    await bus.publish(signal)

    # Execution should see SIGNAL FIRST, then RISK_CHECK
    assert execution.received == [EventType.SIGNAL, EventType.RISK_CHECK], (
        f"Expected [SIGNAL, RISK_CHECK], got {execution.received}"
    )


@pytest.mark.asyncio
async def test_self_emitted_events_still_skipped():
    """Producer == agent.name should still skip self-delivery."""
    bus = SyncEventBus()

    risk = MockAgent(name="risk_mgmt")
    _register(bus, risk, {EventType.RISK_CHECK})

    # risk_mgmt emits its own RISK_CHECK — should be skipped
    await bus.publish(_make_event(EventType.RISK_CHECK, producer="risk_mgmt"))
    assert risk.received == []


@pytest.mark.asyncio
async def test_multiple_nested_events_all_deferred():
    """If processing a parent event triggers multiple nested events,
    they should all be delivered after the parent's subscriber chain."""
    bus = SyncEventBus()

    execution = MockAgent(name="execution")
    _register(bus, execution, {EventType.SIGNAL, EventType.RISK_CHECK, EventType.ORDER_CREATED})

    # Strategy agent emits SIGNAL, which triggers a RISK_CHECK (nested),
    # which itself triggers an ORDER_CREATED (doubly-nested). Use a
    # different producer name for the doubly-nested event so it
    # doesn't get skipped by the execution agent's self-emit filter.
    class ChainedAgent(MockAgent):
        async def on_event(self, event: Event) -> None:
            self.received.append(event.event_type)
            if event.event_type == EventType.SIGNAL:
                await self._bus.publish(_make_event(EventType.RISK_CHECK, producer="risk_mgmt"))
            elif event.event_type == EventType.RISK_CHECK:
                # Producer "broker" so execution doesn't skip it
                await self._bus.publish(_make_event(EventType.ORDER_CREATED, producer="broker"))

    strategy = ChainedAgent(name="strategy_gen")
    strategy._bus = bus
    _register(bus, strategy, {EventType.SIGNAL})
    risk_agent = ChainedAgent(name="risk_mgmt_handler")
    risk_agent._bus = bus
    _register(bus, risk_agent, {EventType.SIGNAL, EventType.RISK_CHECK})

    await bus.publish(_make_event(EventType.SIGNAL, producer="strategy_gen"))

    # Execution's view: SIGNAL, then RISK_CHECK, then ORDER_CREATED
    assert execution.received == [
        EventType.SIGNAL, EventType.RISK_CHECK, EventType.ORDER_CREATED
    ], f"Expected [SIGNAL, RISK_CHECK, ORDER_CREATED], got {execution.received}"


@pytest.mark.asyncio
async def test_top_level_publish_works_without_deferral():
    """A simple publish with no nesting should still work."""
    bus = SyncEventBus()
    agent = MockAgent(name="test_agent")
    _register(bus, agent, {EventType.SIGNAL})
    await bus.publish(_make_event(EventType.SIGNAL, producer="other"))
    assert agent.received == [EventType.SIGNAL]


@pytest.mark.asyncio
async def test_deferred_queue_clears_after_publish():
    """After a publish completes, the deferred queue should be empty."""
    bus = SyncEventBus()

    class EmitterAgent(MockAgent):
        async def on_event(self, event: Event) -> None:
            self.received.append(event.event_type)
            if event.event_type == EventType.SIGNAL:
                await self._bus.publish(_make_event(EventType.RISK_CHECK, producer="risk_mgmt"))

    emitter = EmitterAgent(name="emitter")
    emitter._bus = bus
    _register(bus, emitter, {EventType.SIGNAL})

    await bus.publish(_make_event(EventType.SIGNAL, producer="other"))
    assert len(bus._deferred) == 0, f"Deferred queue should be empty, has {len(bus._deferred)} events"
