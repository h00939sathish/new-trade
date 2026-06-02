import asyncio
import logging

from src.schemas.events import Event, EventType

logger = logging.getLogger("backtest.sync_bus")

class SyncEventBus:
    """
    A synchronous event bus drop-in replacement for AsyncEventBus during backtesting.
    Instead of pushing events into queues for background loops to pick up, this bus
    immediately awaits the agent's `on_event` handler recursively.
    """
    
    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._event_store = None
        self._dropped_events = 0
        
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
        Instead of queueing, route and await immediately.
        """
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
