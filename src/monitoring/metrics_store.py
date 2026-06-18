"""SQLite-backed time-series store for trading metrics.

Schema is narrow (one row per metric+labels per bucket) so that
arbitrary new metrics (Task 22: PnL, exposure, drawdown, etc.)
can be added without schema changes. The Prometheus data model
is the inspiration: a metric is identified by (name, labels),
and the value is summed or set per time bucket.

Persistence is opt-in: ``MetricsCollector`` accepts a
``MetricsStore`` in its constructor. The module-level
``system_metrics`` singleton in :mod:`src.monitoring.metrics`
attaches a default store pointing at ``state/metrics.db`` at
process startup (see :mod:`src.main`).

Why 1-minute buckets
--------------------
Fine-grained enough for sub-minute dashboards (the paper burn-in
runs on 5-minute candles; minute-level metrics are 5x finer than
the data they describe). Coarse-grained enough to keep the table
small over weeks of operation: ~1440 buckets/day, ~43200/month.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger("monitoring.metrics_store")

DEFAULT_DB_PATH = Path("state/metrics.db")
_BUCKET_SECONDS = 60


def bucket_ts(now: float | None = None) -> int:
    """Truncate a unix timestamp to the nearest bucket boundary."""
    ts = now if now is not None else time.time()
    return int(ts // _BUCKET_SECONDS) * _BUCKET_SECONDS


class MetricsStore:
    """Async SQLite time-series store for metric points.

    The store is the durable backing for :class:`MetricsCollector`:
    every counter increment in the collector is also appended to a
    write buffer, which the collector flushes to this store every
    10 seconds (and on shutdown).

    All write methods are idempotent within a bucket: a second
    ``increment(metric, labels)`` in the same minute UPSERTs the
    value (sum) rather than inserting a duplicate row. ``set_gauge``
    uses last-write-wins within a bucket, which is the right
    semantics for absolute values like ``trading_pnl_daily`` and
    ``trading_broker_connected``.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path), timeout=1.0)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_points (
                bucket_ts INTEGER NOT NULL,
                metric TEXT NOT NULL,
                labels TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (bucket_ts, metric, labels)
            )
            """
        )
        await self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_metric_points_metric
                ON metric_points (metric, bucket_ts)
            """
        )
        await self._conn.commit()
        self._initialized = True

    async def increment(
        self,
        metric: str,
        labels: dict[str, str] | None = None,
        delta: float = 1.0,
    ) -> None:
        """Add ``delta`` to a counter metric in the current bucket."""
        await self._ensure_init()
        assert self._conn is not None
        labels_json = json.dumps(labels or {}, sort_keys=True)
        await self._conn.execute(
            """
            INSERT INTO metric_points (bucket_ts, metric, labels, value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bucket_ts, metric, labels)
            DO UPDATE SET value = value + excluded.value
            """,
            (bucket_ts(), metric, labels_json, float(delta)),
        )

    async def set_gauge(
        self,
        metric: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge metric to an absolute value in the current bucket.

        Gauges UPSERT with last-write-wins within a bucket — the
        last sample of the minute is the value that survives, which
        matches Prometheus client semantics for ``Gauge.set()``.
        """
        await self._ensure_init()
        assert self._conn is not None
        labels_json = json.dumps(labels or {}, sort_keys=True)
        await self._conn.execute(
            """
            INSERT INTO metric_points (bucket_ts, metric, labels, value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bucket_ts, metric, labels)
            DO UPDATE SET value = excluded.value
            """,
            (bucket_ts(), metric, labels_json, float(value)),
        )

    async def load_recent_totals(
        self, window_seconds: int = 30 * 24 * 3600
    ) -> dict[tuple[str, str], float]:
        """Sum all (metric, labels) values from the last ``window_seconds``.

        Used by ``MetricsCollector`` on startup to repopulate the
        in-memory cache so ``prometheus_text()`` survives a process
        restart. Returns ``{(metric_name, labels_json): total_value}``.
        """
        await self._ensure_init()
        assert self._conn is not None
        cutoff = bucket_ts(time.time() - window_seconds)
        cursor = await self._conn.execute(
            """
            SELECT metric, labels, SUM(value)
            FROM metric_points
            WHERE bucket_ts >= ?
            GROUP BY metric, labels
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {(m, lbl): float(v) for m, lbl, v in rows}

    async def flush(self) -> None:
        """Commit any pending writes. Cheap (WAL is sync=NORMAL)."""
        if self._conn is not None and self._initialized:
            await self._conn.commit()

    async def close(self) -> None:
        """Flush and close the underlying connection. Idempotent."""
        if self._conn is not None and self._initialized:
            try:
                await self._conn.commit()
                await self._conn.close()
            except Exception as exc:  # pragma: no cover - close best-effort
                logger.warning("MetricsStore close failed: %s", exc)
            self._initialized = False
            self._conn = None
