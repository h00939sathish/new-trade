#!/usr/bin/env python3
"""
P2.4 — 30-day paper trading harness.

Runs the trading system in paper mode continuously during NSE market
hours. Designed to run on Railway (auto-restarts on crash) or on a
local machine during the day.

Outputs:
  - logs/attribution_<date>.jsonl   per-day attribution (P2.2)
  - logs/runtime_traces/*.jsonl     per-event latency (already wired)
  - state/burnin/reconciliation.jsonl  5-minute reconciliation (P1.3)
  - state/trading_events.db          full event SQLite (already wired)

Daily checklist (manually review after each trading day):
  1. At least 1 closed trade per day (BUY→FILL, SELL→FILL, PnL recorded)
  2. Reconciliation clean (no position_drift events)
  3. No unhandled exceptions in logs
  4. Attribution data written to logs/attribution_<date>.jsonl
  5. No STRATEGY_DECAY events (or if any, they were actioned)

Usage:
  Local:   python scripts/run_paper_30d.py
  Railway: configure start command as `python scripts/run_paper_30d.py`
           and ensure TRA_LIVE_TRADING_ENABLED=false (paper mode is default)

Environment variables (all optional):
  TRA_WATCHLIST           Comma-separated symbols (default: from .env)
  TRA_MAX_RUNTIME_MINUTES  Cap runtime; default 390 (6.5h = full NSE day)
  TRA_BURNIN               0=off, 1=on (default: 1 in paper mode)
  TRA_BURNIN_RECONCILE_SECONDS  Default 300
"""
import os
import sys
import asyncio
import logging
from datetime import UTC, datetime, time as dtime, timedelta
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# NSE market hours in IST (9:15-15:30 IST = 3:45-10:00 UTC)
MARKET_OPEN_UTC = dtime(3, 45)
MARKET_CLOSE_UTC = dtime(10, 0)
SQUARE_OFF_START_UTC = dtime(9, 30)  # 15:00 IST — start closing positions
SQUARE_OFF_END_UTC = dtime(10, 0)    # 15:30 IST — force close

logger = logging.getLogger("paper_30d")
logging.basicConfig(
    level=os.getenv("TRA_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def is_market_open(now_utc: datetime | None = None) -> bool:
    now = now_utc or datetime.now(UTC)
    return MARKET_OPEN_UTC <= now.time() <= MARKET_CLOSE_UTC


def is_weekday(now_utc: datetime | None = None) -> bool:
    now = now_utc or datetime.now(UTC)
    return now.weekday() < 5  # 0=Monday, 6=Sunday


def is_square_off_window(now_utc: datetime | None = None) -> bool:
    now = now_utc or datetime.now(UTC)
    return SQUARE_OFF_START_UTC <= now.time() <= SQUARE_OFF_END_UTC


def seconds_until_next_window(now_utc: datetime | None = None) -> float:
    """If market is closed, return seconds until next market open.
    If market is open, return 0.
    If weekend, return seconds until Monday 03:45 UTC.
    """
    now = now_utc or datetime.now(UTC)
    if is_market_open(now) and is_weekday(now):
        return 0.0
    # Find next market open
    next_open = now.replace(hour=MARKET_OPEN_UTC.hour, minute=MARKET_OPEN_UTC.minute, second=0, microsecond=0)
    if now.time() >= MARKET_CLOSE_UTC or not is_weekday(now):
        next_open += timedelta(days=1)
    # Skip weekends
    while next_open.weekday() >= 5:
        next_open += timedelta(days=1)
    return (next_open - now).total_seconds()


def daily_attribution_check() -> dict:
    """Run the attribution aggregator and write a daily summary.

    Returns the summary dict so the caller can log or act on it.
    """
    try:
        from src.analytics.attribution import AttributionAggregator
        agg = AttributionAggregator()
        # Bootstrap from the SQLite event store so we capture
        # everything that happened today.
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        agg.load_from_db(since=today)
        path = agg.write_daily_report(out_dir="logs")
        summary = agg.get_summary()
        logger.info(
            "Daily attribution written: %s | strategies=%d | total_trades=%d",
            path,
            len(summary),
            sum(s.get("trades", 0) for s in summary.values()),
        )
        return summary
    except Exception as e:
        logger.error("Daily attribution check failed: %s", e, exc_info=True)
        return {}


async def wait_for_market_open() -> None:
    """Sleep until the next market-open window."""
    while True:
        secs = seconds_until_next_window()
        if secs <= 0:
            return
        # Log every hour
        if secs > 3600:
            logger.info("Market closed, sleeping %.0fh until open", secs / 3600)
            await asyncio.sleep(3600)
        else:
            logger.info("Market closed, sleeping %.0fm until open", secs / 60)
            await asyncio.sleep(max(1.0, secs))


async def daily_attribution_loop() -> None:
    """Run attribution check at 11:00 UTC (16:30 IST) every weekday."""
    while True:
        now = datetime.now(UTC)
        # Target 11:00 UTC (post-close) on the next weekday
        target = now.replace(hour=11, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        while target.weekday() >= 5:
            target += timedelta(days=1)
        secs = (target - now).total_seconds()
        logger.info("Daily attribution scheduled in %.1fh", secs / 3600)
        await asyncio.sleep(secs)
        summary = daily_attribution_check()
        if summary:
            for strat, s in summary.items():
                logger.info(
                    "  %s: trades=%d pnl=%.2f sharpe=%.2f winrate=%.1f%%",
                    strat, s.get("trades", 0), s.get("total_pnl", 0.0),
                    s.get("sharpe_20", 0.0), s.get("win_rate", 0.0) * 100,
                )


async def main() -> None:
    max_runtime_min = int(os.getenv("TRA_MAX_RUNTIME_MINUTES", "390"))
    started_at = datetime.now(UTC)
    logger.info("=" * 60)
    logger.info("PAPER 30-DAY HARNESS STARTED (max_runtime=%d min)", max_runtime_min)
    logger.info("=" * 60)

    # Schedule daily attribution at end-of-day
    attrib_task = asyncio.create_task(daily_attribution_loop(), name="daily_attribution")

    # Run the actual trading system in a subprocess
    # We delegate to src.main.run() so the harness uses the canonical entry point
    try:
        from src.main import run as run_system
        await run_system()
    finally:
        attrib_task.cancel()
        # Final attribution snapshot
        daily_attribution_check()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Harness interrupted by user")
    except Exception as e:
        logger.error("Harness crashed: %s", e, exc_info=True)
        sys.exit(1)
