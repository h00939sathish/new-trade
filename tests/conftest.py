"""Shared pytest configuration and fixtures for the NSE trading system.

Test isolation contract
=======================
The production order database lives at ``state/order_state.db`` (see
``src/agents/execution.py`` module-level constant ``_ORDER_DB_PATH``).
Production trading state must never be touched by tests.

Two layers of protection make accidental writes to ``state/`` impossible:

1. **Module-level autouse fixture** ``isolated_order_db`` (this file)
   monkeypatches ``_ORDER_DB_PATH`` to a per-test ``tmp_path`` directory
   before any test runs, and restores it afterwards. This means any
   ``ExecutionAgent()`` constructed without an explicit ``order_db_path``
   argument will write to an isolated temp file rather than production
   state.

2. **Session-start defensive cleanup** below deletes any
   ``state/test_*.db`` and ``state/probe_*.db`` files that may have
   leaked from older test runs. New code cannot create files matching
   those globs (the autouse fixture redirects the default), but
   historical leaks are scrubbed here.

For tests that need an explicit DB path (e.g. to share with a
hand-written fixture or assert on the file), use the named
``order_state_db`` or ``events_db`` fixtures — they return the same
``tmp_path`` location the autouse monkeypatch points at.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Session-start cleanup (defense in depth against historical leaks)
# ---------------------------------------------------------------------------


def pytest_sessionstart():
    """Remove test artifacts that may have leaked to the worktree.

    Runs once per ``pytest`` invocation. If you add a new test that
    writes a DB outside of ``tmp_path``, add a glob for it here.
    """
    # Root-level events DB (created by tests that build a full
    # TradingSystem in CWD). CWD-relative paths are unsafe; tests
    # should prefer tmp_path fixtures instead.
    for stem in ("trading_events.db",):
        for suffix in ("", "-wal", "-shm"):
            db = Path(stem + suffix)
            if db.exists():
                db.unlink()

    # Historical leaks in state/ from older test runs that did not
    # redirect the default DB path. The .gitignore already prevents
    # these from being committed; this hook prevents them from
    # accumulating in the worktree.
    state_dir = Path("state")
    if state_dir.is_dir():
        for pattern in ("test_*.db", "probe_*.db"):
            for db in state_dir.glob(pattern):
                db.unlink(missing_ok=True)

    # Historical cache directory from a one-off data fetch.
    import shutil

    cache_dir = Path("data/historical")
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Per-test DB isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def order_state_db(tmp_path) -> Path:
    """Return an isolated order-state DB path for a single test.

    Use this when a test (or its fixture) needs the DB path as an
    explicit value, e.g.::

        def test_x(order_state_db):
            agent = ExecutionAgent(order_db_path=order_state_db)

    The path lives under pytest's per-test ``tmp_path`` and is
    automatically removed at test teardown.
    """
    return tmp_path / "order_state.db"


@pytest.fixture
def events_db(tmp_path) -> Path:
    """Return an isolated events-DB path for a single test."""
    return tmp_path / "events.db"


@pytest.fixture(autouse=True)
def isolated_order_db(monkeypatch, tmp_path):
    """Auto-apply: redirect the default order DB to a per-test tmp_path.

    Patches ``src.agents.execution._ORDER_DB_PATH`` so that any
    ``ExecutionAgent()`` constructed during a test (including the seven
    tests in this repo that do not pass ``order_db_path`` explicitly)
    writes to a temp file rather than the production
    ``state/order_state.db``.

    The patch is reverted at test teardown by ``monkeypatch``'s
    function-scoped cleanup. No state persists between tests.

    Tests that need the DB path for assertions can request the
    ``order_state_db`` named fixture, which returns the same path.
    """
    db_path = tmp_path / "order_state.db"
    monkeypatch.setattr("src.agents.execution._ORDER_DB_PATH", db_path)
    return db_path
