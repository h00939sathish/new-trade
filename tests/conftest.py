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

    import shutil

    cache_dir = Path("data/historical")
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
        except Exception:
            pass
