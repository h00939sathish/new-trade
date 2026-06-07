from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from src.event_store.base import EventStore
from src.schemas.events import Event


class InMemoryEventStore(EventStore):
    def __init__(self):
        self._events: dict[str, list[Event]] = {}
        self._all_events: list[Event] = []
        self._position: int = 0
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._events.clear()
        self._all_events.clear()
        self._position = 0
        self._connected = False

    async def append(self, stream: str, event: Event) -> int:
        self._position += 1
        event.position = self._position
        if stream not in self._events:
            self._events[stream] = []
        self._events[stream].append(event)
        self._all_events.append(event)
        return self._position

    async def append_batch(self, stream: str, events: list[Event]) -> list[int]:
        positions: list[int] = []
        for event in events:
            pos = await self.append(stream, event)
            positions.append(pos)
        return positions

    async def read(
        self,
        stream: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        stream_events = self._events.get(stream, [])
        result = []
        for event in stream_events:
            if event.position is not None and event.position > offset:
                result.append(event)
            if len(result) >= limit:
                break
        return result

    async def replay(
        self,
        stream: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[Event]:
        source = self._events.get(stream, []) if stream else self._all_events
        for event in source:
            if after and event.timestamp < after:
                continue
            if before and event.timestamp > before:
                continue
            yield event

    async def get_latest(self, stream: str) -> Event | None:
        stream_events = self._events.get(stream, [])
        if not stream_events:
            return None
        return stream_events[-1]

    async def get_stream_names(self) -> list[str]:
        return list(self._events.keys())

    async def get_stream_length(self, stream: str) -> int:
        return len(self._events.get(stream, []))

    async def delete_stream(self, stream: str) -> None:
        if stream in self._events:
            del self._events[stream]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "type": "memory",
            "streams": len(self._events),
            "total_events": len(self._all_events),
        }
