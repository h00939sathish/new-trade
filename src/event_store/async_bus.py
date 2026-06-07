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
        self._persistence_tasks: set[asyncio.Task] = set()
        self._persistence_errors: int = 0

    def set_event_store(self, event_store) -> None:
        self._event_store = event_store

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    @property
    def persistence_pending(self) -> int:
        return len(self._persistence_tasks)

    @property
    def persistence_errors(self) -> int:
        return self._persistence_errors

    async def drain_persistence_tasks(self, timeout: float | None = None) -> bool:
        if not self._persistence_tasks:
            return True

        _, pending = await asyncio.wait(tuple(self._persistence_tasks), timeout=timeout)
        if pending:
            logger.error(
                "Timed out draining %d event persistence task(s)",
                len(pending),
            )
            return False
        return True

    def subscribe(self, agent_name: str, event_types: set[EventType]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100000)
        for et in event_types:
            etype_str = et.value if hasattr(et, "value") else str(et)
            self._subscribers.setdefault(etype_str, []).append(queue)
        return queue

    async def publish(self, event: Event) -> None:
        # Fan-out to subscriber queues
        etype_str = (
            event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        )
        queues = self._subscribers.get(etype_str, [])
        is_critical = event.event_type in _CRITICAL_EVENT_TYPES
        for queue in queues:
            try:
                # Add backpressure: wait up to 0.5s for queue to drain
                await asyncio.wait_for(queue.put(event), timeout=0.5)
            except TimeoutError:
                self._dropped_events += 1
                if is_critical:
                    # For critical events, drop oldest to make room — log at ERROR
                    try:
                        dropped = queue.get_nowait()
                        queue.put_nowait(event)
                        logger.error(
                            "Event bus FULL: dropped older event %s to deliver critical %s "
                            "(total dropped: %d)",
                            dropped.event_type.value,
                            event.event_type.value,
                            self._dropped_events,
                        )
                    except Exception:
                        logger.error(
                            "Event bus FULL: FAILED to deliver critical event %s "
                            "(total dropped: %d)",
                            event.event_type.value,
                            self._dropped_events,
                        )
                else:
                    # Non-critical: log at warning
                    logger.warning(
                        "Event bus FULL: dropped event %s (total dropped: %d, queue_size: %d)",
                        event.event_type.value,
                        self._dropped_events,
                        queue.qsize(),
                    )

        # Persist to event store
        if self._event_store:
            from src.event_store.memory import InMemoryEventStore

            if isinstance(self._event_store, InMemoryEventStore):
                await self._event_store.append("events.bus", event)
            else:
                # For SQLite/Timescale, write in a background task
                task = asyncio.create_task(self._persist_event(self._event_store, event))
                self._persistence_tasks.add(task)
                task.add_done_callback(self._persistence_tasks.discard)

    async def _persist_event(self, event_store, event: Event) -> None:
        try:
            await event_store.append("events.bus", event)
        except Exception:
            self._persistence_errors += 1
            logger.exception(
                "Failed to persist event %s (%s)",
                event.event_id,
                event.event_type.value,
            )


# Singleton instance
event_bus = AsyncEventBus()
