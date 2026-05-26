import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from src.event_store.base import EventStore
from src.schemas.events import Event


class SqliteEventStore(EventStore):
    def __init__(self, db_path: str | Path = "trading_events.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return

        async with self._write_lock:
            if self._conn is not None:
                return

            def _conn_setup():
                self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        position INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        event_type TEXT NOT NULL,
                        stream TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        data TEXT NOT NULL,
                        metadata TEXT NOT NULL
                    )
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_stream
                    ON events(stream, position)
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_timestamp
                    ON events(timestamp)
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_type
                    ON events(event_type)
                """)
                self._conn.commit()

            await asyncio.to_thread(_conn_setup)

    async def disconnect(self) -> None:
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            msg = "Event store not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._conn

    async def append(self, stream: str, event: Event) -> int:
        conn = self._get_conn()

        def _db_append():
            cursor = conn.execute(
                """
                INSERT INTO events (event_id, event_type, stream, timestamp, data, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    stream,
                    event.timestamp.isoformat(),
                    json.dumps(event.data, default=str),
                    event.metadata.model_dump_json(),
                ),
            )
            conn.commit()
            return cursor.lastrowid

        async with self._write_lock:
            position = await asyncio.to_thread(_db_append)
        if position is not None:
            event.position = position
        return position or 0

    async def append_batch(self, stream: str, events: list[Event]) -> list[int]:
        conn = self._get_conn()

        def _db_append_batch():
            positions: list[int] = []
            for event in events:
                cursor = conn.execute(
                    """
                    INSERT INTO events (event_id, event_type, stream, timestamp, data, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type.value,
                        stream,
                        event.timestamp.isoformat(),
                        json.dumps(event.data, default=str),
                        event.metadata.model_dump_json(),
                    ),
                )
                pos = cursor.lastrowid
                if pos is not None:
                    event.position = pos
                    positions.append(pos)
            conn.commit()
            return positions

        async with self._write_lock:
            return await asyncio.to_thread(_db_append_batch)

    async def read(
        self,
        stream: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        conn = self._get_conn()

        def _db_read():
            return conn.execute(
                """
                SELECT * FROM events
                WHERE stream = ? AND position > ?
                ORDER BY position ASC
                LIMIT ?
                """,
                (stream, offset, limit),
            ).fetchall()

        rows = await asyncio.to_thread(_db_read)
        return [self._row_to_event(r) for r in rows]

    async def replay(
        self,
        stream: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[Event]:
        conn = self._get_conn()

        def _db_replay():
            query = "SELECT * FROM events WHERE 1=1"
            params: list[Any] = []
            if stream:
                query += " AND stream = ?"
                params.append(stream)
            if after:
                query += " AND timestamp >= ?"
                params.append(after.isoformat())
            if before:
                query += " AND timestamp <= ?"
                params.append(before.isoformat())
            query += " ORDER BY position ASC LIMIT 10000"
            return conn.execute(query, params).fetchall()

        rows = await asyncio.to_thread(_db_replay)
        for row in rows:
            yield self._row_to_event(row)

    async def get_latest(self, stream: str) -> Event | None:
        conn = self._get_conn()

        def _db_get_latest():
            return conn.execute(
                """
                SELECT * FROM events
                WHERE stream = ?
                ORDER BY position DESC
                LIMIT 1
                """,
                (stream,),
            ).fetchone()

        row = await asyncio.to_thread(_db_get_latest)
        if row is None:
            return None
        return self._row_to_event(row)

    async def get_stream_names(self) -> list[str]:
        conn = self._get_conn()

        def _db_get_stream_names():
            return conn.execute(
                "SELECT DISTINCT stream FROM events ORDER BY stream"
            ).fetchall()

        rows = await asyncio.to_thread(_db_get_stream_names)
        return [r["stream"] for r in rows]

    async def get_stream_length(self, stream: str) -> int:
        conn = self._get_conn()

        def _db_get_stream_length():
            return conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE stream = ?",
                (stream,),
            ).fetchone()

        row = await asyncio.to_thread(_db_get_stream_length)
        return row["cnt"] if row else 0

    async def delete_stream(self, stream: str) -> None:
        conn = self._get_conn()

        def _db_delete_stream():
            conn.execute("DELETE FROM events WHERE stream = ?", (stream,))
            conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_db_delete_stream)

    async def health_check(self) -> dict[str, Any]:
        try:
            conn = self._get_conn()

            def _db_health():
                conn.execute("SELECT 1")

            await asyncio.to_thread(_db_health)
            return {"status": "healthy", "type": "sqlite", "path": str(self.db_path)}
        except Exception as e:
            return {"status": "unhealthy", "type": "sqlite", "error": str(e)}

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        event = Event(
            event_id=row["event_id"],
            event_type=str(row["event_type"]),
            stream=row["stream"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            data=json.loads(row["data"]),
            metadata=json.loads(row["metadata"]),
            position=row["position"],
        )
        return event
