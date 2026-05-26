import asyncio
import logging

from src.schemas.events import Event, EventType

logger = logging.getLogger("event_store.bus")

# Critical event types that must NEVER be silently dropped
_CRITICAL_EVENT_TYPES = {
    EventType.RISK_BREACH,
    EventType.RISK_CHECK,
    EventType.ORDER_CREATED,
    EventType.SYSTEM_ERROR,
}

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
        self._dropped_events: int = 0

    def set_event_store(self, event_store) -> None:
        self._event_store = event_store

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    def subscribe(self, agent_name: str, event_types: set[EventType]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        for et in event_types:
            etype_str = et.value if hasattr(et, "value") else str(et)
            self._subscribers.setdefault(etype_str, []).append(queue)
        return queue

    async def publish(self, event: Event) -> None:
        # Fan-out to subscriber queues
        etype_str = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        queues = self._subscribers.get(etype_str, [])
        is_critical = event.event_type in _CRITICAL_EVENT_TYPES
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped_events += 1
                if is_critical:
                    # For critical events, drop oldest to make room — log at ERROR
                    try:
                        dropped = queue.get_nowait()
                        queue.put_nowait(event)
                        logger.error(
                            "Event bus FULL: dropped older event %s to deliver critical %s "
                            "(total dropped: %d)",
                            dropped.event_type.value, event.event_type.value,
                            self._dropped_events,
                        )
                    except Exception:
                        logger.error(
                            "Event bus FULL: FAILED to deliver critical event %s "
                            "(total dropped: %d)",
                            event.event_type.value, self._dropped_events,
                        )
                else:
                    # Non-critical: log at warning
                    logger.warning(
                        "Event bus FULL: dropped event %s (total dropped: %d, queue_size: %d)",
                        event.event_type.value, self._dropped_events, queue.qsize(),
                    )

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

