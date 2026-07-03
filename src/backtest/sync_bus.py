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
        self._agents: list = []
        self._event_store = None
        self._dropped_events = 0
        self._defer_depth = 0
        self._deferred: deque[Event] = deque()

    def set_event_store(self, event_store):
        self._event_store = event_store

    def register_agent(self, agent):
        """Register an agent instance so we can call its on_event directly."""
        if agent not in self._agents:
            self._agents.append(agent)

    def subscribe(self, agent_name: str, event_types: set[EventType]) -> asyncio.Queue:
        """
        Return a dummy queue so that `BaseAgent._subscribe_bus_loop` doesn't crash.
        We will not push events into this queue; we will bypass it entirely.
        """
        return asyncio.Queue(maxsize=1)

    async def publish(self, event: Event) -> None:
        if self._defer_depth > 0:
            self._deferred.append(event)
            return

        self._defer_depth = 1
        try:
            await self._deliver(event)
            while self._deferred:
                self._defer_depth = 1
                nested = self._deferred.popleft()
                await self._deliver(nested)
        finally:
            self._defer_depth = 0
            self._deferred.clear()

    async def _deliver(self, event: Event) -> None:
        for agent in self._agents:
            if event.metadata and event.metadata.producer == agent.name:
                continue
            if getattr(agent, "_running", True) is False:
                continue
            try:
                await agent.on_event(event)
            except Exception as e:
                logger.error(
                    "SyncEventBus: Error calling %s.on_event: %s", agent.name, e, exc_info=True
                )

        if self._event_store:
            from src.event_store.memory import InMemoryEventStore

            if isinstance(self._event_store, InMemoryEventStore):
                await self._event_store.append("events.bus", event)
