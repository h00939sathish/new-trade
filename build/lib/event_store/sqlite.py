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

    async def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path))
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

    async def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            msg = "Event store not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._conn

    async def append(self, stream: str, event: Event) -> int:
        conn = self._get_conn()
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
        position = cursor.lastrowid
        if position is not None:
            event.position = position
        return position or 0

    async def append_batch(self, stream: str, events: list[Event]) -> list[int]:
        conn = self._get_conn()
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

    async def read(
        self,
        stream: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM events
            WHERE stream = ? AND position > ?
            ORDER BY position ASC
            LIMIT ?
            """,
            (stream, offset, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    async def replay(
        self,
        stream: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> AsyncIterator[Event]:
        conn = self._get_conn()
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
        rows = conn.execute(query, params).fetchall()
        for row in rows:
            yield self._row_to_event(row)

    async def get_latest(self, stream: str) -> Event | None:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT * FROM events
            WHERE stream = ?
            ORDER BY position DESC
            LIMIT 1
            """,
            (stream,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event(row)

    async def get_stream_names(self) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT stream FROM events ORDER BY stream"
        ).fetchall()
        return [r["stream"] for r in rows]

    async def get_stream_length(self, stream: str) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE stream = ?",
            (stream,),
        ).fetchone()
        return row["cnt"] if row else 0

    async def delete_stream(self, stream: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM events WHERE stream = ?", (stream,))
        conn.commit()

    async def health_check(self) -> dict[str, Any]:
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
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
