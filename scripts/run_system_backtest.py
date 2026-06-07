import asyncio
import logging
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

# Insert src into path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.system import TradingSystem
from src.backtest.sync_bus import SyncEventBus
import src.event_store.async_bus as async_bus_module
from src.connectors.backtest_provider import BacktestDataProvider
from src.schemas.events import Exchange

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("system_backtest")


async def run(days: int):
    logger.info(f"=== FULL SYSTEM BACKTEST ({days} days) ===")

    # 1. Replace the global AsyncEventBus with our SyncEventBus
    sync_bus = SyncEventBus()
    async_bus_module.event_bus = sync_bus

    # 2. Instantiate System without real broker
    from src.config.settings import settings

    settings.agent_reflection_enabled = (
        False  # Disable reflection during backtest to prevent grid-search loops
    )

    system = TradingSystem(
        providers={"angel": None, "groww": None, "kite_client": None, "kite_broker": None}
    )
    system.execution._paper_trading = True

    # Set watchlist from environment or fallback
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    env_watchlist = os.getenv("TRA_WATCHLIST")
    if env_watchlist:
        watchlist = env_watchlist.split(",")
    else:
        watchlist = ["RELIANCE", "TCS", "HDFCBANK", "INFY"]

    logger.info(f"Using watchlist: {watchlist}")
    system.set_watchlist(watchlist)

    # 3. Prevent their background loops
    for agent in system._agents:
        original_start = agent.start
        import functools

        async def patched_start(*args, orig=original_start, **kwargs):
            return await orig(run_background_loop=False)

        agent.start = patched_start

    # 4. Start system (this now uses patched start and sync bus)
    await system.start()

    # 4b. Register agents to SyncEventBus after on_start has populated subscriptions
    for agent in system._agents:
        sync_bus.register_agent(agent)

    # 5. Fetch Historical Data
    logger.info(f"Fetching {days} days of historical data for {watchlist}...")
    provider = BacktestDataProvider(market_data_provider=None, instruments=watchlist)
    ticks = await provider.get_backtest_ticks(days=days)

    if not ticks:
        logger.error("No historical ticks found!")
        return

    logger.info(f"Loaded {len(ticks)} total ticks. Beginning tick-by-tick simulation...")

    # 6. Run simulation tick-by-tick synchronously
    ticks_processed = 0
    for tick in ticks:
        instrument = tick.get("instrument")
        price = tick.get("price") or tick.get("last_price")
        if not instrument or not price:
            continue

        # This will synchronously cascade through MarketIntel -> StrategyGen -> Risk -> Execution
        # We inject as a 1-minute candle (OHLCV) so that strategies and aggregators process it
        await system.inject_ohlcv(
            instrument=instrument,
            interval="minute",
            open=price,
            high=price,
            low=price,
            close=price,
            volume=tick.get("volume", 0),
            exchange="NSE",
            timestamp=tick.get("timestamp"),
        )
        ticks_processed += 1
        if ticks_processed % 10000 == 0:
            logger.info(f"Processed {ticks_processed} / {len(ticks)} ticks...")

    # 7. Print Performance Results from Execution Agent
    logger.info("=== SIMULATION COMPLETE ===")
    logger.info(f"Total Ticks Processed: {ticks_processed}")

    exec_agent = system.get_agent("execution")
    if exec_agent:
        fills = getattr(exec_agent, "_filled_orders", {})
        total_fills = sum(len(f) for f in fills.values())
        logger.info(f"Total Trade Fills Generated: {total_fills}")

    portfolio = system.get_agent("portfolio_opt")
    if portfolio:
        health = await portfolio.health()
        logger.info(f"Total P&L: {health.get('total_pnl', 0.0):.2f}")
        logger.info(f"Current Capital: {health.get('current_capital', 0.0):.2f}")
        logger.info(f"Total Positions: {health.get('total_positions', 0)}")

    logger.info("Stopping trading system gracefully...")

    # Stop cleanly
    await system.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.days))
