#!/usr/bin/env python3
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

try:
    from openbb import obb
except ImportError:
    obb = None

logger = logging.getLogger("pipeline.openbb_download")

SYMBOLS = [
    "RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK",
    "SBIN", "LT", "ITC", "AXISBANK", "KOTAKBANK",
]

INTERVALS = {
    "1m": {"days": 60, "file": "1m.parquet"},
    "5m": {"days": 60, "file": "5m.parquet"},
    "15m": {"days": 60, "file": "15m.parquet"},
    "1d": {"days": 365 * 10, "file": "1d.parquet"},
}

DATA_DIRS = [
    Path("data/raw"),
    Path("data/parquet"),
    Path("data/processed"),
]


def _ensure_dirs() -> None:
    for d in DATA_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def _resolve_obb() -> bool:
    try:
        from openbb import obb
        globals()["obb"] = obb
        return True
    except Exception as e:
        logger.warning("Failed to import openbb: %s", e)
        return False


def _load_cached(symbol: str, interval: str) -> pd.DataFrame | None:
    path = Path(f"data/parquet/{symbol}/{INTERVALS[interval]['file']}")
    if path.exists():
        try:
            df = pd.read_parquet(path)
            logger.info("Loaded cached %s %s (%d rows)", symbol, interval, len(df))
            return df
        except Exception as e:
            logger.warning("Failed to read cache %s: %s", path, e)
    return None


def _save_parquet(df: pd.DataFrame, symbol: str, interval: str) -> Path:
    subdir = Path(f"data/parquet/{symbol}")
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / INTERVALS[interval]["file"]
    df.to_parquet(path, index=False)
    logger.info("Saved %s %s -> %s (%d rows)", symbol, interval, path, len(df))

    for d in DATA_DIRS:
        if d.name == "parquet":
            continue
        target = d / symbol / INTERVALS[interval]["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(target, index=False)

    return path


def download_symbol(
    symbol: str,
    interval: str,
    start_date: str | None = None,
    end_date: str | None = None,
    provider: str = "yfinance",
) -> pd.DataFrame | None:
    cached = _load_cached(symbol, interval)
    if cached is not None:
        return cached

    try:
        cfg = INTERVALS[interval]
        end = end_date or datetime.now(UTC).strftime("%Y-%m-%d")
        if start_date is None:
            start = (datetime.now(UTC) - timedelta(days=cfg["days"])).strftime("%Y-%m-%d")

        yahoo_symbol = f"{symbol}.NS"
        data = obb.equity.price.historical(
            yahoo_symbol,
            provider=provider,
            interval=interval,
            start_date=start,
            end_date=end,
        )
        df = data.to_dataframe()
        if df is None or df.empty:
            logger.warning("No data returned for %s %s", symbol, interval)
            return None

        df = df.reset_index()
        if "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})

        if "timestamp" not in df.columns:
            df["timestamp"] = datetime.now(UTC).isoformat()

        _save_parquet(df, symbol, interval)
        return df

    except Exception as e:
        logger.error("Failed to download %s %s: %s", symbol, interval, e)
        return None


def download_all(
    symbols: list[str] | None = None,
    intervals: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    _ensure_dirs()
    if not _resolve_obb():
        logger.error("OpenBB not available — cannot download")
        return {}

    targets = symbols or SYMBOLS
    intvs = intervals or list(INTERVALS.keys())
    stats: dict[str, dict[str, int]] = {}

    for symbol in targets:
        stats[symbol] = {}
        for interval in intvs:
            logger.info("Downloading %s %s ...", symbol, interval)
            df = download_symbol(symbol, interval)
            stats[symbol][interval] = len(df) if df is not None else 0

    return stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stats = download_all()
    total = 0
    print("\nDownload summary:")
    print(f"{'Symbol':<12s}" + "".join(f"{k:>10s}" for k in INTERVALS) + f"{'Total':>10s}")
    print("-" * (12 + 10 * (len(INTERVALS) + 1)))
    for symbol, intervals in stats.items():
        row_total = sum(intervals.values())
        total += row_total
        counts = "".join(f"{intervals.get(k, 0):>10d}" for k in INTERVALS)
        print(f"{symbol:<12s}{counts}{row_total:>10d}")
    print("-" * (12 + 10 * (len(INTERVALS) + 1)))
    print(f"{'TOTAL':<12s}{'':>10s}{'':>10s}{'':>10s}{'':>10s}{total:>10d}")


if __name__ == "__main__":
    main()
