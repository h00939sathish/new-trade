"""
LOOP 6 — Weekly Loop
=====================
Trigger:  Sunday / End of trading week
Steps:
  Research Review -> Champion Challenge -> Promote/Demote
  -> Generate Alpha Report -> Repeat
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.weekly_loop")

WEEKLY_STATE = Path("state/weekly_loop_state.json")


async def step_research_review():
    logger.info("Weekly Loop: Research Review")
    research_dir = Path("reports/research")
    if research_dir.exists():
        pending = []
        for md_file in sorted(research_dir.glob("*.md")):
            content = md_file.read_text()
            if "- [ ] Pending Review" in content:
                pending.append(md_file.name)
                logger.info("  Pending review: %s", md_file.name)
        if not pending:
            logger.info("  No pending research hypotheses")
        return pending
    return []


async def step_champion_challenge():
    logger.info("Weekly Loop: Champion Challenge")
    from src.champion import ChampionRegistry
    registry = ChampionRegistry()
    champions = registry.get_all_champions()
    logger.info("  Current champions: %d categories", len(champions))
    for cat, champ in champions.items():
        logger.info("    %s: %s (Sharpe=%.2f)", cat, champ.get("strategy_name"), champ.get("metrics", {}).get("sharpe", 0))
    return champions


async def step_alpha_report():
    logger.info("Weekly Loop: Generate Alpha Report")
    try:
        from src.monitoring.strategy_scoreboard import StrategyScoreboard
        scoreboard = StrategyScoreboard()
        rankings = scoreboard.get_rankings()
        report_path = Path("reports") / f"alpha_report_{datetime.now(UTC).strftime('%Y%m%d')}.md"
        lines = [
            f"# Weekly Alpha Report — {datetime.now(UTC).strftime('%Y-%m-%d')}",
            "",
            "## Strategy Rankings",
            "",
            "| Rank | Strategy | Trades | PnL | Sharpe | Win Rate |",
            "|------|----------|--------|-----|--------|----------|",
        ]
        for i, s in enumerate(rankings[:10], 1):
            lines.append(
                f"| {i} | {s.get('strategy','?')} | {s.get('trades_count',0)} | "
                f"{s.get('pnl',0):.2f} | {s.get('sharpe',0):.2f} | {s.get('win_rate',0):.1%} |"
            )
        report_path.write_text("\n".join(lines))
        logger.info("  Alpha report generated: %s", report_path)
        return str(report_path)
    except Exception as e:
        logger.error("  Alpha report failed: %s", e)
        return None


async def run_weekly_loop():
    logger.info("=" * 60)
    logger.info("WEEKLY LOOP STARTING — %s", datetime.now(UTC).strftime("%Y-%m-%d"))
    logger.info("=" * 60)

    results = {
        "research_review": await step_research_review(),
        "champion_challenge": await step_champion_challenge(),
        "alpha_report": await step_alpha_report(),
    }

    WEEKLY_STATE.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_STATE.write_text(
        json.dumps(
            {
                "last_run": datetime.now(UTC).isoformat(),
                "results": {k: str(v) if not isinstance(v, list) else v for k, v in results.items()},
            },
            indent=2,
            default=str,
        )
    )

    logger.info("=" * 60)
    logger.info("WEEKLY LOOP COMPLETE")
    logger.info("=" * 60)
    return results


if __name__ == "__main__":
    asyncio.run(run_weekly_loop())
