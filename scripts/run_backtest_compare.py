"""
Dual backtest runner: 1-year and 5-year backtest with side-by-side comparison.
Uses Walk-Forward Validation on the strategies that have parameter grids defined.
Supports stuck-detection via progress + time-per-window logging.
"""

import asyncio
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.walk_forward import WalkForwardValidator
from src.config.strategy_config import STRATEGY_REGISTRY
from src.connectors.backtest_provider import BacktestDataProvider

logging.basicConfig(level=logging.INFO, force=True)
for h in logging.root.handlers:
    h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    h.flush = h.flush  # type: ignore[attr-defined]

logger = logging.getLogger("backtest_compare")


def _ts() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def _print_comparison(results: dict[str, dict[str, Any]], duration_map: dict[str, float]):
    """Pretty-print a comparison table of all backtest runs."""
    print("\n" + "=" * 90)
    print(f"{'COMPARISON RESULTS':^90}")
    print("=" * 90)

    headers = [
        "Horizon",
        "Strategy",
        "Total Trades",
        "Win Rate",
        "Profit Factor",
        "Sharpe Ratio",
        "Max Drawdown",
        "Final Value",
        "Duration",
    ]

    col_w = [
        10,
        18,
        14,
        12,
        14,
        14,
        14,
        14,
        10,
    ]

    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, col_w)))
    print("  " + "--".join("-" * w for w in col_w))

    for (horizon, strategy), res in results.items():
        duration_str = f"{duration_map.get((horizon, strategy), 0.0):.1f}s"
        if duration_map.get((horizon, strategy), 0.0) > 60:
            duration_str = f"{duration_map[(horizon, strategy)] / 60:.1f}m"

        row = [
            horizon,
            strategy,
            str(res.get("total_trades", 0)),
            f"{res.get('win_rate', 0.0) * 100:.1f}%",
            f"{res.get('profit_factor', 0.0):.3f}",
            f"{res.get('sharpe_ratio', 0.0):.3f}",
            f"{res.get('max_drawdown', 0.0) * 100:.1f}%",
            f"{res.get('final_value', 0.0):,.0f}",
            duration_str,
        ]
        print("  " + "  ".join(r.ljust(w) for r, w in zip(row, col_w)))

    print("=" * 90 + "\n")


async def run_single_backtest(
    name: str,
    ticks: list[dict[str, Any]],
    train_days: int,
    test_days: int,
    grid: dict[str, dict[str, list[Any]]],
    initial_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    """Run a walk-forward backtest for a single strategy and report results."""
    validator = WalkForwardValidator(
        train_days=train_days,
        test_days=test_days,
        initial_capital=initial_capital,
        parameter_grids={name: grid},
    )
    start = time.perf_counter()
    try:
        logger.info(f"[{name}] Starting backtest | ticks={len(ticks):,}")
        result = await validator.run_validation(name, ticks, metric="sharpe_ratio")
        elapsed = time.perf_counter() - start
        oos = result.get("overall_oos_performance", {})
        logger.info(
            "[%s] Done in %.1fs | trades=%d | sharpe=%.3f | final=%s",
            name,
            elapsed,
            oos.get("total_trades", 0),
            oos.get("sharpe_ratio", 0.0),
            f"{oos.get('final_value', 0.0):,.0f}",
        )
        oos["_elapsed_seconds"] = elapsed
        return result
    except Exception as e:
        elapsed = time.perf_counter() - start
        logger.error("[%s] FAILED after %.1fs: %s", name, elapsed, e)
        return {"error": str(e), "strategy": name, "_elapsed_seconds": elapsed}


async def _run_dual():
    years_options = [1, 5]

    # Instruments: use all 25 for 1y, top 5 for 5y to keep runtime sane
    all_nifty50 = [
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
    subset5 = all_nifty50[:5]

    # Training/test windows: for 1y use 270/90, for 5y use 1440/180
    # (floor to available days in data)
    validation_grid = {
        "orb": {
            "volume_multiplier": [1.0, 1.2, 1.5],
            "atr_window": [14],
        },
        "vol_compression": {
            "bb_window": [20],
            "lookback": [100, 50],
            "percentile_threshold": [20.0, 30.0],
        },
        "tsmom": {
            "target_volatility": [0.10],
            "horizons": [(60, 120, 250), (20, 60, 120)],
        },
        "sideways_reversion": {
            "rsi_window": [14],
            "bb_window": [20],
        },
    }

    strategies_to_test = ["orb", "vol_compression", "tsmom", "sideways_reversion"]

    all_results: dict[tuple[str, str], dict[str, Any]] = {}
    duration_map: dict[tuple[str, str], float] = {}
    all_ticks: dict[int, list[dict[str, Any]]] = {}

    for years in years_options:
        days = years * 365
        instruments = all_nifty50 if years == 1 else subset5
        horizon_label = f"{years}yr"
        test_days = 90 if years == 1 else 180
        train_days = 270 if years == 1 else 1440

        logger.info("=" * 60)
        logger.info("  Backtest horizon: %s  |  instruments: %d", horizon_label, len(instruments))
        logger.info("  train_days=%d  test_days=%d", train_days, test_days)
        logger.info("=" * 60)

        # Reuse cached ticks if we already fetched this horizon
        if days not in all_ticks:
            provider = BacktestDataProvider(
                market_data_provider=None,
                instruments=instruments,
            )
            logger.info("[%s] Fetching %d days of data...", horizon_label, days)
            fetch_start = time.perf_counter()
            ticks = await provider.get_backtest_ticks(days=days)
            fetch_elapsed = time.perf_counter() - fetch_start
            ticks.sort(key=lambda t: t.get("timestamp") or "")
            all_ticks[days] = ticks
            logger.info(
                "[%s] Fetched %d ticks in %.1fs (%.0f ticks/s)",
                horizon_label,
                len(ticks),
                fetch_elapsed,
                len(ticks) / max(fetch_elapsed, 0.01),
            )
        else:
            ticks = all_ticks[days]
            logger.info("[%s] Reusing cached tick batch (%d ticks).", horizon_label, len(ticks))

        # Run each strategy
        for sname in strategies_to_test:
            if sname not in STRATEGY_REGISTRY:
                logger.warning("[%s] Skipping %s — not in registry.", horizon_label, sname)
                continue
            if sname not in validation_grid:
                logger.warning("[%s] Skipping %s — no parameter grid.", horizon_label, sname)
                continue

            result = await run_single_backtest(
                name=sname,
                ticks=ticks,
                train_days=train_days,
                test_days=test_days,
                grid=validation_grid,
                initial_capital=1_000_000.0,
            )
            oos = result.get("overall_oos_performance", result) if "error" not in result else result
            all_results[(horizon_label, sname)] = oos
            duration_map[(horizon_label, sname)] = result.get("_elapsed_seconds", 0.0)

    _print_comparison(all_results, duration_map)
    return all_results, duration_map


if __name__ == "__main__":
    total_start = time.perf_counter()
    try:
        asyncio.run(_run_dual())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
    total_elapsed = time.perf_counter() - total_start
    logger.info("All backtests completed in %.1fs (%.1fm)", total_elapsed, total_elapsed / 60)
