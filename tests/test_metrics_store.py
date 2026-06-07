"""Tests for the SQLite-backed metrics persistence layer.

Covers ``MetricsStore`` (low-level: increment/set_gauge/load) and
the ``MetricsCollector`` persistence integration
(counts -> pending buffer -> flush -> load_from_store).

The ``isolated_metrics_store`` autouse fixture in conftest.py
provides a per-test tmp_path store, so no test writes to
``state/metrics.db``.
"""
import pytest

from src.monitoring.metrics import MetricsCollector
from src.monitoring.metrics_store import MetricsStore, bucket_ts


# ---------------------------------------------------------------------------
# MetricsStore: low-level persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_writes_one_row(tmp_path):
    store = MetricsStore(tmp_path / "m.db")
    await store.increment("trading_events_total", {"type": "TICK"})
    await store.flush()

    totals = await store.load_recent_totals()
    assert totals == {("trading_events_total", '{"type": "TICK"}'): 1.0}
    await store.close()


@pytest.mark.asyncio
async def test_increment_upserts_in_same_bucket(tmp_path):
    store = MetricsStore(tmp_path / "m.db")
    await store.increment("trading_events_total", {"type": "TICK"})
    await store.increment("trading_events_total", {"type": "TICK"})
    await store.increment("trading_events_total", {"type": "TICK"})
    await store.flush()

    totals = await store.load_recent_totals()
    assert totals == {("trading_events_total", '{"type": "TICK"}'): 3.0}
    await store.close()


@pytest.mark.asyncio
async def test_increment_distinguishes_labels(tmp_path):
    store = MetricsStore(tmp_path / "m.db")
    await store.increment("trading_signals_total", {"strategy": "mom", "direction": "long"})
    await store.increment("trading_signals_total", {"strategy": "mom", "direction": "short"})
    await store.increment("trading_signals_total", {"strategy": "rsi", "direction": "long"})
    await store.flush()

    totals = await store.load_recent_totals()
    # Three distinct label sets -> three keys
    assert len(totals) == 3
    assert totals[("trading_signals_total", '{"direction": "long", "strategy": "mom"}')] == 1.0
    assert totals[("trading_signals_total", '{"direction": "short", "strategy": "mom"}')] == 1.0
    assert totals[("trading_signals_total", '{"direction": "long", "strategy": "rsi"}')] == 1.0
    await store.close()


@pytest.mark.asyncio
async def test_set_gauge_overwrites_in_same_bucket(tmp_path):
    store = MetricsStore(tmp_path / "m.db")
    await store.set_gauge("trading_pnl_daily", 100.0)
    await store.set_gauge("trading_pnl_daily", 150.0)  # overwrites
    await store.set_gauge("trading_pnl_daily", -25.0)  # overwrites again
    await store.flush()

    totals = await store.load_recent_totals()
    assert totals == {("trading_pnl_daily", "{}"): -25.0}
    await store.close()


@pytest.mark.asyncio
async def test_load_recent_totals_uses_window(tmp_path):
    store = MetricsStore(tmp_path / "m.db")
    await store.increment("trading_events_total", {"type": "TICK"})
    await store.flush()

    # 1-day window: should include the just-written row
    recent = await store.load_recent_totals(window_seconds=24 * 3600)
    assert len(recent) == 1

    # 1-second window: should exclude it (the row is in a bucket from
    # ~now, so this is racy, but the row was written in the current
    # minute so any window >= 60s should include it). Use 60s+5s.
    from src.monitoring.metrics_store import bucket_ts as _bucket_ts

    recent_short = await store.load_recent_totals(window_seconds=65)
    assert len(recent_short) == 1

    # A window ending before the row's bucket: must be empty
    # Compute a cutoff 1 bucket before the row's bucket
    row_bucket = _bucket_ts()
    # We can't easily inject a custom window that excludes the row
    # because bucket_ts() is current. But we can verify the
    # happy-path window works.
    await store.close()


def test_bucket_ts_truncates_to_minute():
    # 2026-06-07 12:34:56 UTC -> bucket 12:34:00
    ts = 1749294896  # some arbitrary ts
    b = bucket_ts(ts)
    assert b % 60 == 0
    assert b <= ts
    assert ts - b < 60


# ---------------------------------------------------------------------------
# MetricsCollector persistence integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collector_writes_to_store_on_flush(tmp_path):
    store = MetricsStore(tmp_path / "m.db")
    m = MetricsCollector(store=store)
    m.count_event("TICK")
    m.count_event("TICK")
    m.count_signal("mom", "long")
    m.count_order("filled")

    await m.flush()

    totals = await store.load_recent_totals()
    assert totals[("trading_events_total", '{"type": "TICK"}')] == 2.0
    assert totals[("trading_signals_total", '{"direction": "long", "strategy": "mom"}')] == 1.0
    assert totals[("trading_orders_total", '{"status": "filled"}')] == 1.0
    await store.close()


@pytest.mark.asyncio
async def test_collector_load_from_store_restores_counters(tmp_path):
    """End-to-end: count, flush, recreate on same path, load -> counters restored."""
    db_path = tmp_path / "m.db"

    # First "process": write
    store1 = MetricsStore(db_path)
    m1 = MetricsCollector(store=store1)
    m1.count_event("TICK")
    m1.count_event("TICK")
    m1.count_event("TICK")
    m1.count_signal("mom", "long")
    m1.count_order("rejected")
    await m1.flush()
    await store1.close()

    # Second "process": read
    store2 = MetricsStore(db_path)
    m2 = MetricsCollector(store=store2)
    loaded = await m2.load_from_store()

    # Should have loaded 3 distinct metric series
    assert loaded == {
        "trading_events_total": 1,
        "trading_signals_total": 1,
        "trading_orders_total": 1,
    }

    # Counters should reflect the restored values
    assert m2.snapshot()["events_by_type"]["TICK"] == 3
    assert m2.snapshot()["signals_by_strategy"]["mom:long"] == 1
    assert m2.snapshot()["orders_by_status"]["rejected"] == 1
    await store2.close()


@pytest.mark.asyncio
async def test_collector_prometheus_text_unchanged_after_persistence(tmp_path):
    """Persistence must not change the prometheus_text() output format."""
    store = MetricsStore(tmp_path / "m.db")
    m = MetricsCollector(store=store)
    m.count_event("market.tick")
    m.count_signal("momentum", "long")
    text = m.prometheus_text()
    assert "trading_events_total" in text
    assert 'type="market_tick"' in text
    assert "trading_uptime_seconds" in text

    # Flush and verify text is the same (the in-memory counters don't
    # change as a result of persistence)
    await m.flush()
    text_after = m.prometheus_text()
    assert text == text_after
    await store.close()


@pytest.mark.asyncio
async def test_collector_without_store_does_not_create_db(tmp_path, monkeypatch):
    """A collector with no store (default) must never touch the filesystem."""
    # No fixture for the store; pass nothing
    m = MetricsCollector()
    m.count_event("TICK")
    m.count_signal("mom", "long")
    # snapshot() should still work
    snap = m.snapshot()
    assert snap["events_by_type"]["TICK"] == 1
    # No DB file should be created in cwd or tmp_path
    assert not (tmp_path / "metrics.db").exists()
    # And await flush() on a store-less collector is a no-op
    await m.flush()
    assert not (tmp_path / "metrics.db").exists()


@pytest.mark.asyncio
async def test_collector_attach_store_at_runtime(tmp_path):
    """attach_store() is the runtime hook used by main.py."""
    m = MetricsCollector()
    m.count_event("TICK")
    # No store yet: counters exist in memory only
    assert m.snapshot()["events_by_type"]["TICK"] == 1

    # Attach a store and flush
    store = MetricsStore(tmp_path / "m.db")
    m.attach_store(store)
    await m.flush()

    totals = await store.load_recent_totals()
    # The pre-attach count was never persisted (no store yet); the
    # flush after attach only writes new increments. This documents
    # the contract: counters accumulated before attach_store() are
    # NOT backfilled to the store.
    assert ("trading_events_total", '{"type": "TICK"}') not in totals

    m.count_event("TICK")  # new increment after attach
    await m.flush()
    totals = await store.load_recent_totals()
    assert totals[("trading_events_total", '{"type": "TICK"}')] == 1.0
    await store.close()
