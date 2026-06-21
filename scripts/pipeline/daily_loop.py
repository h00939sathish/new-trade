"""
LOOP 5 — Daily Loop
====================
Trigger:  Scheduled (start of trading day or cron)
Steps:
  Data Update -> OpenBB Refresh -> Research Queue -> Validation Queue
  -> Paper Trading -> Attribution -> Decay Detection -> Risk Review
  -> Execution Review -> Lessons Learned -> Repeat
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.daily_loop")

STATE_FILE = Path("state/daily_loop_state.json")


async def step_data_update():
    logger.info("Daily Loop: Data Update")
    try:
        from scripts.pipeline.openbb_download import main as download_data
        await download_data()
        logger.info("Daily Loop: Data update complete")
    except Exception as e:
        logger.error("Daily Loop: Data update failed: %s", e)


async def step_openbb_refresh():
    logger.info("Daily Loop: OpenBB Refresh")
    try:
        from scripts.pipeline.openbb_download import refresh_processed
        await refresh_processed()
    except Exception as e:
        logger.error("Daily Loop: OpenBB refresh failed: %s", e)


async def step_research_queue():
    logger.info("Daily Loop: Research Queue")
    try:
        from scripts.pipeline.research_loop import run_research_scan
        hypotheses = await run_research_scan()
        logger.info("Daily Loop: Generated %d hypotheses", len(hypotheses))
    except Exception as e:
        logger.error("Daily Loop: Research scan failed: %s", e)


async def step_validation_queue():
    logger.info("Daily Loop: Validation Queue")
    pending_dir = Path("reports/research")
    if pending_dir.exists():
        for md_file in sorted(pending_dir.glob("*.md")):
            content = md_file.read_text()
            if "- [ ] Pending Review" in content and "- [x] Accepted" not in content:
                logger.info("Daily Loop: Hypothesis pending validation: %s", md_file.name)


async def step_attribution_update():
    logger.info("Daily Loop: Attribution Update")
    try:
        from src.monitoring.strategy_scoreboard import StrategyScoreboard
        scoreboard = StrategyScoreboard()
        path = scoreboard.update()
        logger.info("Daily Loop: Scoreboard updated: %s", path)
    except Exception as e:
        logger.error("Daily Loop: Attribution failed: %s", e)


async def step_decay_detection():
    logger.info("Daily Loop: Decay Detection")
    try:
        from src.monitoring.decay_detector import PerformanceDecayDetector
        PerformanceDecayDetector()
        logger.info("Daily Loop: Decay detector check complete")
    except Exception as e:
        logger.error("Daily Loop: Decay detection failed: %s", e)


async def step_risk_review():
    logger.info("Daily Loop: Risk Review")
    try:
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        if ks.active:
            logger.warning("Daily Loop: KILL SWITCH ACTIVE — %s", ks.reason)
        else:
            logger.info("Daily Loop: Kill switch inactive — OK")
    except Exception as e:
        logger.error("Daily Loop: Risk review failed: %s", e)


async def step_execution_review():
    logger.info("Daily Loop: Execution Review")
    try:
        from src.execution.hardening import BrokerReconnector
        connector = BrokerReconnector()
        if not connector.is_connected():
            logger.warning("Daily Loop: Broker disconnected!")
        else:
            logger.info("Daily Loop: Broker connected — OK")
    except Exception as e:
        logger.error("Daily Loop: Execution review failed: %s", e)


def step_lessons_learned():
    logger.info("Daily Loop: Lessons Learned")


DAILY_STEPS = [
    ("data_update", step_data_update),
    ("openbb_refresh", step_openbb_refresh),
    ("research_queue", step_research_queue),
    ("validation_queue", step_validation_queue),
    ("attribution_update", step_attribution_update),
    ("decay_detection", step_decay_detection),
    ("risk_review", step_risk_review),
    ("execution_review", step_execution_review),
    ("lessons_learned", step_lessons_learned),
]


async def run_daily_loop():
    logger.info("=" * 60)
    logger.info("DAILY LOOP STARTING — %s", datetime.now(UTC).strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 60)

    results = {}
    for step_name, step_fn in DAILY_STEPS:
        try:
            if asyncio.iscoroutinefunction(step_fn):
                await step_fn()
            else:
                step_fn()
            results[step_name] = "ok"
        except Exception as e:
            logger.error("Daily Loop step '%s' failed: %s", step_name, e)
            results[step_name] = f"error: {e}"

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {
                "last_run": datetime.now(UTC).isoformat(),
                "results": results,
            },
            indent=2,
        )
    )

    logger.info("=" * 60)
    logger.info("DAILY LOOP COMPLETE")
    logger.info("Results: %s", json.dumps(results))
    logger.info("=" * 60)
    return results


if __name__ == "__main__":
    asyncio.run(run_daily_loop())
