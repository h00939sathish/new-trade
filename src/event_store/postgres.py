import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import asyncpg

from src.config.settings import settings
from src.event_store.base import EventStore
from src.schemas.events import Event

logger = logging.getLogger("event_store.postgres")


class PostgresEventStore(EventStore):
    _SCHEMA_VERSION = 1

    def __init__(self, dsn: str):
        self.dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._pool: asyncpg.Pool | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._pool and not self._pool.is_closing():
            return

        async with self._connect_lock:
            if self._pool and not self._pool.is_closing():
                return

            pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
            try:
                async with pool.acquire() as conn:
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS events (
                            position BIGSERIAL PRIMARY KEY,
                            event_id TEXT NOT NULL UNIQUE,
                            event_type TEXT NOT NULL,
                            stream TEXT NOT NULL,
                            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            data JSONB NOT NULL,
                            metadata JSONB NOT NULL
                        )
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_events_stream
                        ON events(stream, position)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_events_timestamp
                        ON events(timestamp)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_events_type
                        ON events(event_type)
                    """)
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS _schema_version (
                            version INTEGER NOT NULL
                        )
                    """)
                    row = await conn.fetchrow("SELECT version FROM _schema_version")
                    if row is None:
                        await conn.execute(
                            "INSERT INTO _schema_version (version) VALUES ($1)",
                            self._SCHEMA_VERSION,
                        )
                    elif row["version"] != self._SCHEMA_VERSION:
                        await pool.close()
                        raise RuntimeError(
                            f"Postgres event store schema version mismatch: "
                            f"stored={row['version']}, expected={self._SCHEMA_VERSION}. "
                            "Run migrations or recreate the database."
                        )
                    if settings.timescaledb_enabled:
                        try:
                            await conn.execute("""
                                SELECT create_hypertable('events', 'timestamp',
                                    if_not_exists => TRUE)
                            """)
                        except Exception as e:
                            logger.warning(
                                "Failed to create TimescaleDB hypertable (extension might be missing): %s. "
                                "Continuing with standard Postgres table.",
                                e,
                            )
            except Exception:
                await pool.close()
                raise

            self._pool = pool

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None or self._pool.is_closing():
            msg = "Event store not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._pool

    async def append(self, stream: str, event: Event) -> int:
        pool = self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO events (event_id, event_type, stream, timestamp, data, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                RETURNING position
                """,
                event.event_id,
                event.event_type.value,
                stream,
                event.timestamp,
                json.dumps(event.data, default=str),
                event.metadata.model_dump_json(),
            )
            position = row["position"]
            event.position = position
            return position

    async def append_batch(self, stream: str, events: list[Event]) -> list[int]:
        pool = self._get_pool()
        positions: list[int] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO events (event_id, event_type, stream, timestamp, data, metadata)
                        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                        RETURNING position
                        """,
                        event.event_id,
                        event.event_type.value,
                        stream,
                        event.timestamp,
                        json.dumps(event.data, default=str),
                        event.metadata.model_dump_json(),
                    )
                    pos = row["position"]
                    event.position = pos
                    positions.append(pos)
        return positions

    async def read(
        self,
        stream: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        pool = self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM events
                WHERE stream = $1 AND position > $2
                ORDER BY position ASC
                LIMIT $3
                """,
                stream,
                offset,
                limit,
            )
            return [self._row_to_event(r) for r in rows]

    async def replay(
        self,
        stream: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[Event]:
        pool = self._get_pool()
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        idx = 1
        if stream:
            query += f" AND stream = ${idx}"
            idx += 1
            params.append(stream)
        if after:
            query += f" AND timestamp >= ${idx}"
            idx += 1
            params.append(after)
        if before:
            query += f" AND timestamp <= ${idx}"
            idx += 1
            params.append(before)
        query += " ORDER BY position ASC"
        async with pool.acquire() as conn:
            async with conn.transaction():
                async for row in conn.cursor(query, *params):
                    yield self._row_to_event(row)

    async def get_latest(self, stream: str) -> Event | None:
        pool = self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM events
                WHERE stream = $1
                ORDER BY position DESC
                LIMIT 1
                """,
                stream,
            )
            if row is None:
                return None
            return self._row_to_event(row)

    async def get_stream_names(self) -> list[str]:
        pool = self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT stream FROM events ORDER BY stream")
            return [r["stream"] for r in rows]

    async def get_stream_length(self, stream: str) -> int:
        pool = self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE stream = $1",
                stream,
            )
            return row or 0

    async def delete_stream(self, stream: str) -> None:
        pool = self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM events WHERE stream = $1",
                stream,
            )

    async def health_check(self) -> dict[str, Any]:
        try:
            pool = self._get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"status": "healthy", "type": "postgres"}
        except Exception as e:
            return {"status": "unhealthy", "type": "postgres", "error": str(e)}

    def _row_to_event(self, row: asyncpg.Record) -> Event:
        return Event(
            event_id=row["event_id"],
            event_type=row["event_type"],
            stream=row["stream"],
            timestamp=row["timestamp"],
            data=dict(row["data"]),
            metadata=dict(row["metadata"]),
            position=row["position"],
        )
