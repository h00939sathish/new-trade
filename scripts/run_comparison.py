import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("comparison")


async def run():
    logger.info("==========================================")
    logger.info("   1-YEAR vs 5-YEAR BACKTEST COMPARISON   ")
    logger.info("==========================================")

    script_path = Path("scripts/run_validation.py")
    out_1yr = Path("results_1yr.json")
    out_5yr = Path("results_5yr.json")

    # 1. Run 1-year Backtest
    logger.info("\n--- Starting 1-Year Backtest (365 days) ---")
    cmd_1yr = [
        sys.executable,
        str(script_path),
        "--days",
        "365",
        "--train_days",
        "180",
        "--test_days",
        "30",
        "--output",
        str(out_1yr),
    ]
    proc1 = subprocess.run(cmd_1yr, capture_output=False)
    if proc1.returncode != 0:
        logger.error("1-year backtest failed.")
        return

    # 2. Run 5-year Backtest
    logger.info("\n--- Starting 5-Year Backtest (1825 days) ---")
    # For 5 years, let's use 1 year training and 90 days test.
    cmd_5yr = [
        sys.executable,
        str(script_path),
        "--days",
        "1825",
        "--train_days",
        "365",
        "--test_days",
        "90",
        "--output",
        str(out_5yr),
    ]
    proc2 = subprocess.run(cmd_5yr, capture_output=False)
    if proc2.returncode != 0:
        logger.error("5-year backtest failed.")
        return

    # 3. Compare Results
    logger.info("\n==========================================")
    logger.info("          COMPARISON RESULTS              ")
    logger.info("==========================================\n")

    try:
        with open(out_1yr) as f:
            res_1yr = json.load(f)
        with open(out_5yr) as f:
            res_5yr = json.load(f)

        strategies = set(res_1yr.keys()).union(set(res_5yr.keys()))

        for strat in strategies:
            logger.info(f"Strategy: {strat.upper()}")

            s_1yr = res_1yr.get(strat, {})
            s_5yr = res_5yr.get(strat, {})

            r_1yr = s_1yr.get("total_return", 0.0) * 100
            sr_1yr = s_1yr.get("sharpe_ratio", 0.0)
            dd_1yr = s_1yr.get("max_drawdown", 0.0) * 100

            r_5yr = s_5yr.get("total_return", 0.0) * 100
            sr_5yr = s_5yr.get("sharpe_ratio", 0.0)
            dd_5yr = s_5yr.get("max_drawdown", 0.0) * 100

            logger.info(
                f"  1-Year -> Return: {r_1yr:.2f}%, Sharpe: {sr_1yr:.2f}, MaxDD: {dd_1yr:.2f}%"
            )
            logger.info(
                f"  5-Year -> Return: {r_5yr:.2f}%, Sharpe: {sr_5yr:.2f}, MaxDD: {dd_5yr:.2f}%"
            )
            logger.info("-" * 40)

    except Exception as e:
        logger.error(f"Error comparing results: {e}")


if __name__ == "__main__":
    asyncio.run(run())
