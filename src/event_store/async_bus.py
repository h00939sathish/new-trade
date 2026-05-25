import asyncio
from typing import Any
from src.schemas.events import Event, EventType

class AsyncEventBus:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
        
    def __init__(self):
        if self._initialized:
            return
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._event_store = None
        self._initialized = True
        
    def set_event_store(self, event_store) -> None:
        self._event_store = event_store
        
    def subscribe(self, agent_name: str, event_types: set[EventType]) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=2000)
        for et in event_types:
            etype_str = et.value if hasattr(et, "value") else str(et)
            self._subscribers.setdefault(etype_str, []).append(queue)
        return queue
        
    async def publish(self, event: Event) -> None:
        # Fan-out to subscriber queues
        etype_str = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        queues = self._subscribers.get(etype_str, [])
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Remove oldest and retry if full, or log warning
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:
                    pass
        
        # Persist to event store
        if self._event_store:
            from src.event_store.memory import InMemoryEventStore
            if isinstance(self._event_store, InMemoryEventStore):
                await self._event_store.append("events.bus", event)
            else:
                # For SQLite/Timescale, write in a background task
                asyncio.create_task(self._event_store.append("events.bus", event))

# Singleton instance
event_bus = AsyncEventBus()
