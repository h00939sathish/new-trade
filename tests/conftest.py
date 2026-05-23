from pathlib import Path


def pytest_sessionstart():
    db = Path("trading_events.db")
    if db.exists():
        db.unlink()

    wal = Path("trading_events.db-wal")
    if wal.exists():
        wal.unlink()

    shm = Path("trading_events.db-shm")
    if shm.exists():
        shm.unlink()
