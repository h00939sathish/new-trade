import fnmatch
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

from src.schemas.events import Event


class EventStoreConfig:
    batch_size: int = 100
    replay_chunk_size: int = 1000


class EventStore(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def append(self, stream: str, event: Event) -> int: ...

    @abstractmethod
    async def append_batch(self, stream: str, events: list[Event]) -> list[int]: ...

    @abstractmethod
    async def read(
        self,
        stream: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]: ...

    @abstractmethod
    async def replay(
        self,
        stream: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[Event]: ...

    @abstractmethod
    async def get_latest(self, stream: str) -> Event | None: ...

    @abstractmethod
    async def get_stream_names(self) -> list[str]: ...

    async def match_streams(self, pattern: str) -> list[str]:
        all_streams = await self.get_stream_names()
        return [s for s in all_streams if fnmatch.fnmatch(s, pattern)]

    @abstractmethod
    async def get_stream_length(self, stream: str) -> int: ...

    @abstractmethod
    async def delete_stream(self, stream: str) -> None: ...

    async def subscribe(
        self,
        stream: str,
        callback: Callable[[Event], Any],
        from_position: int = -1,
    ) -> None:
        last_pos = from_position
        while True:
            events = await self.read(stream, offset=last_pos + 1, limit=10)
            for event in events:
                if event.position is not None:
                    last_pos = event.position
                await callback(event)
            if not events:
                import asyncio

                await asyncio.sleep(0.1)

    @abstractmethod
    async def health_check(self) -> dict[str, Any]: ...
