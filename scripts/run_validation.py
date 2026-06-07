import asyncio
import logging
import sys
from pathlib import Path

# Ensure src is importable without relying on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.walk_forward import WalkForwardValidator
from src.connectors.backtest_provider import BacktestDataProvider
from src.config.strategy_config import STRATEGY_REGISTRY

logging.basicConfig(level=logging.INFO, force=True)
for h in logging.root.handlers:
    h.setFormatter(logging.Formatter("%(message)s"))
    try:
        h.flush = h.flush  # type: ignore[attr-defined]
    except Exception:
        pass

logger = logging.getLogger("validation")


import argparse

import json


async def run(days: int, train_days: int, test_days: int, output_path: str = ""):
    logger.info(f"Fetching backtest data for validation ({days} days, Nifty 50)...")
    sys.stdout.flush()

    nifty50_symbols = [
        "RELIANCE",
        "HDFCBANK",
        "INFY",
        "ICICIBANK",
        "TCS",
        "ITC",
        "LT",
        "SBIN",
        "BHARTIARTL",
        "BAJFINANCE",
        "KOTAKBANK",
        "AXISBANK",
        "ASIANPAINT",
        "MARUTI",
        "SUNPHARMA",
        "TITAN",
        "HINDUNILVR",
        "TATAMOTORS",
        "M&M",
        "ULTRACEMCO",
        "NTPC",
        "POWERGRID",
        "BAJAJFINSV",
        "TATASTEEL",
        "HCLTECH",
    ]

    # We use daily or 1m data provider
    provider = BacktestDataProvider(market_data_provider=None, instruments=nifty50_symbols)
    # Fetch specified days of data
    logger.info(f"Calling provider.get_backtest_ticks(days={days})...")
    sys.stdout.flush()
    ticks = await provider.get_backtest_ticks(days=days)
    logger.info("Backtest ticks fetched.")
    sys.stdout.flush()

    # Custom grid for our new strategies
    validation_grid = {
        "orb": {"volume_multiplier": [1.0, 1.2, 1.5], "atr_window": [14]},
        "vol_compression": {
            "bb_window": [20],
            "lookback": [100, 50],
            "percentile_threshold": [20.0, 30.0],
        },
        "tsmom": {"target_volatility": [0.10], "horizons": [(60, 120, 250), (20, 60, 120)]},
        "sideways_reversion": {"rsi_window": [14], "bb_window": [20]},
    }

    validator = WalkForwardValidator(
        train_days=train_days,
        test_days=test_days,
        initial_capital=1000000.0,
        parameter_grids=validation_grid,
    )

    strategies_to_test = ["orb", "vol_compression", "tsmom", "sideways_reversion"]

    final_results = {}

    for strategy in strategies_to_test:
        if strategy not in STRATEGY_REGISTRY:
            logger.warning(f"Strategy {strategy} not found in registry. Skipping.")
            continue

        logger.info(f"Starting Walk-Forward Validation for {strategy}...")
        try:
            result = await validator.run_validation(strategy, ticks, metric="sharpe_ratio")
            logger.info(f"=== Results for {strategy} ===")
            logger.info(f"Overall OOS Performance: {result['overall_oos_performance']}")
            logger.info("=" * 30)
            final_results[strategy] = result["overall_oos_performance"]
        except Exception as e:
            logger.error(f"Validation failed for {strategy}: {e}")

    if output_path:
        with open(output_path, "w") as f:
            json.dump(final_results, f, indent=2)
        logger.info(f"Results saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run walk-forward validation.")
    parser.add_argument("--days", type=int, default=365, help="Total days of data to fetch")
    parser.add_argument("--train_days", type=int, default=180, help="Days for training window")
    parser.add_argument("--test_days", type=int, default=30, help="Days for testing window")
    parser.add_argument("--output", type=str, default="", help="Path to save results JSON")
    args = parser.parse_args()

    asyncio.run(
        run(
            days=args.days,
            train_days=args.train_days,
            test_days=args.test_days,
            output_path=args.output,
        )
    )
