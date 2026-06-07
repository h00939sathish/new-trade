import asyncio
import logging
from collections import deque

from src.schemas.events import Event, EventType

logger = logging.getLogger("backtest.sync_bus")


class SyncEventBus:
    """
    A synchronous event bus drop-in replacement for AsyncEventBus during backtesting.
    Instead of pushing events into queues for background loops to pick up, this bus
    immediately awaits the agent's `on_event` handler.

    FIX S2.1: nested events emitted inside an `on_event` handler (e.g., risk_mgmt
    emitting RISK_CHECK while processing a SIGNAL) are queued and delivered ONLY
    after the parent event's subscriber chain completes. Without this deferral,
    the bus delivered RISK_CHECK to execution BEFORE the original SIGNAL, so
    execution's _pending_signals dict was empty when the risk check arrived —
    every order-creation was silently dropped. This is the root cause of
    "0 fills" in the system backtester even though all the strategies
    produce signals and risk approves them.
    """

    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._event_store = None
        self._dropped_events = 0
        self._defer_depth = 0
        self._deferred: deque[Event] = deque()

    def set_event_store(self, event_store):
        self._event_store = event_store

    def register_agent(self, agent):
        """Register an agent instance so we can call its on_event directly."""
        for et in agent._subscribed_event_types:
            etype_str = et.value if hasattr(et, "value") else str(et)
            self._subscribers.setdefault(etype_str, []).append(agent)

    def subscribe(self, agent_name: str, event_types: set[EventType]) -> asyncio.Queue:
        """
        Return a dummy queue so that `BaseAgent._subscribe_bus_loop` doesn't crash.
        We will not push events into this queue; we will bypass it entirely.
        """
        return asyncio.Queue(maxsize=1)

    async def publish(self, event: Event) -> None:
        """
        If we are already inside a publish (nested call), defer delivery until
        the outer publish completes. This guarantees that all subscribers of
        the parent event are called before any nested event is delivered.
        """
        if self._defer_depth > 0:
            # Nested publish — queue for later
            self._deferred.append(event)
            return

        # Top-level publish — process synchronously, draining nested events
        # one at a time so depth accounting is correct for N-deep nesting.
        self._defer_depth = 1
        try:
            # First, deliver the top-level event
            await self._deliver(event)
            # Then drain any nested events that were queued. Each nested event
            # is itself processed via _deliver, and any tertiary-nested events
            # it emits are appended to the same queue. We re-enter depth=1
            # for each so that any new events emitted during its handling
            # are also deferred.
            while self._deferred:
                self._defer_depth = 1
                nested = self._deferred.popleft()
                await self._deliver(nested)
        finally:
            self._defer_depth = 0
            # Any stragglers (shouldn't happen but defensive)
            self._deferred.clear()

    async def _deliver(self, event: Event) -> None:
        etype_str = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        agents = self._subscribers.get(etype_str, [])

        for agent in agents:
            # Skip self-emitted events
            if event.metadata and event.metadata.producer == agent.name:
                continue

            try:
                await agent.on_event(event)
            except Exception as e:
                logger.error("SyncEventBus: Error calling %s.on_event: %s", agent.name, e, exc_info=True)

        # Optional: Append to memory store
        if self._event_store:
            from src.event_store.memory import InMemoryEventStore
            if isinstance(self._event_store, InMemoryEventStore):
                await self._event_store.append("events.bus", event)
