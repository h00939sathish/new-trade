"""
LOOP 7 — Monthly Loop
======================
Trigger:  1st of month
Steps:
  Full Audit -> Remove Complexity -> Archive Dead Strategies
  -> Improve Alpha -> Repeat
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.monthly_loop")

MONTHLY_STATE = Path("state/monthly_loop_state.json")


async def step_full_audit():
    logger.info("Monthly Loop: Full Audit")
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "strategy_count": 0,
        "active_strategies": [],
        "dead_strategies": [],
        "issues": [],
    }
    try:
        from src.config.strategy_config import load_strategy_config
        cfg = load_strategy_config()
        strategies = cfg.get("strategies", {})
        report["strategy_count"] = len(strategies)
        for name, sc in strategies.items():
            if sc.get("enabled", True):
                report["active_strategies"].append(name)
            else:
                report["dead_strategies"].append(name)
        logger.info("  Active: %d, Disabled: %d", len(report["active_strategies"]), len(report["dead_strategies"]))
    except Exception as e:
        logger.error("  Audit failed: %s", e)
        report["issues"].append(str(e))
    return report


async def step_archive_dead():
    logger.info("Monthly Loop: Archive Dead Strategies")
    try:
        from src.monitoring.strategy_scoreboard import StrategyScoreboard

        scoreboard = StrategyScoreboard()
        rankings = scoreboard.get_rankings()
        decay_candidates = [s for s in rankings if s.get("sharpe", 1.0) < 0.5 and s.get("trades_count", 0) > 20]

        if decay_candidates:
            logger.info("  Candidates for decay: %s", [s.get("strategy") for s in decay_candidates])
        else:
            logger.info("  No strategies with significant decay detected")
        return [s.get("strategy") for s in decay_candidates]
    except Exception as e:
        logger.error("  Archive check failed: %s", e)
        return []


async def step_remove_complexity():
    logger.info("Monthly Loop: Remove Complexity")
    try:
        old_reports = list(Path("reports/research").glob("*.md"))
        for f in old_reports:
            age_days = (datetime.now(UTC) - datetime.fromtimestamp(f.stat().st_mtime, UTC)).days
            if age_days > 90:
                f.unlink()
                logger.info("  Removed old report: %s (age: %dd)", f.name, age_days)
    except Exception as e:
        logger.error("  Cleanup failed: %s", e)


async def step_improve_alpha():
    logger.info("Monthly Loop: Improve Alpha")
    try:
        from scripts.pipeline.research_loop import run_research_scan
        hypotheses = await run_research_scan()
        logger.info("  Generated %d new research hypotheses", len(hypotheses))
        return len(hypotheses)
    except Exception as e:
        logger.error("  Alpha improvement failed: %s", e)
        return 0


async def run_monthly_loop():
    logger.info("=" * 60)
    logger.info("MONTHLY LOOP STARTING — %s", datetime.now(UTC).strftime("%Y-%m"))
    logger.info("=" * 60)

    results = {
        "audit": await step_full_audit(),
        "archive_dead": await step_archive_dead(),
        "remove_complexity": await step_remove_complexity(),
        "improve_alpha": await step_improve_alpha(),
    }

    MONTHLY_STATE.parent.mkdir(parents=True, exist_ok=True)
    MONTHLY_STATE.write_text(
        json.dumps(
            {
                "last_run": datetime.now(UTC).isoformat(),
                "results": results,
            },
            indent=2,
            default=str,
        )
    )

    logger.info("=" * 60)
    logger.info("MONTHLY LOOP COMPLETE")
    logger.info("=" * 60)
    return results


if __name__ == "__main__":
    asyncio.run(run_monthly_loop())
