"""
LOOP 1 — Research Loop
=======================
Trigger:  OpenBB scan completes OR weekly research slot opens
Action:
  1. OpenBB downloads fresh data -> parquet
  2. ResearchAgent scans: market structure, volatility regimes, factor data
  3. ResearchAgent generates <=5 hypotheses/week -> reports/research/*.md
  4. Human reviews in dashboard
  5. Accepted -> Validation Queue | Rejected -> archive
Stop:     Budget reached (5/week) or no viable hypotheses
Verify:   reports/research/{date}_{strategy}.md with measurable success criteria
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.research_loop")

HYPOTHESIS_BUDGET_PATH = Path("state/research_budget.json")
REPORTS_DIR = Path("reports/research")
MAX_HYPOTHESES_PER_WEEK = 5


def _load_budget() -> dict:
    if HYPOTHESIS_BUDGET_PATH.exists():
        try:
            return json.loads(HYPOTHESIS_BUDGET_PATH.read_text())
        except Exception:
            pass
    return {"week_start": None, "count": 0, "hypotheses": []}


def _save_budget(budget: dict) -> None:
    HYPOTHESIS_BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    HYPOTHESIS_BUDGET_PATH.write_text(json.dumps(budget, indent=2, default=str))


def _check_budget() -> bool:
    budget = _load_budget()
    now = datetime.now(UTC)
    week_start = now.isocalendar()
    current_week_key = f"{week_start[0]}-W{week_start[1]:02d}"

    if budget.get("week_start") != current_week_key:
        budget = {"week_start": current_week_key, "count": 0, "hypotheses": []}

    if budget["count"] >= MAX_HYPOTHESES_PER_WEEK:
        logger.warning(
            "Research budget exhausted: %d/%d this week", budget["count"], MAX_HYPOTHESES_PER_WEEK
        )
        return False

    return True


def _increment_budget(hypothesis: dict) -> None:
    budget = _load_budget()
    now = datetime.now(UTC)
    week_start = now.isocalendar()
    current_week_key = f"{week_start[0]}-W{week_start[1]:02d}"

    if budget.get("week_start") != current_week_key:
        budget = {"week_start": current_week_key, "count": 0, "hypotheses": []}

    budget["count"] += 1
    budget["hypotheses"].append(hypothesis)
    _save_budget(budget)


async def run_research_scan() -> list[dict]:
    """Run one research scan: loads strategies, runs grid search, outputs hypotheses."""
    if not _check_budget():
        return []

    from src.research.agent import ResearchAgent

    agent = ResearchAgent()
    await agent.on_start()

    hypotheses = []
    strategies_to_scan = ["momentum", "sideways_reversion", "vwap_reversion", "stat_arb"]

    for strategy_name in strategies_to_scan:
        logger.info("Research scanning: %s", strategy_name)
        hypothesis = await agent.generate_hypothesis(strategy_name)
        if hypothesis:
            hypotheses.append(hypothesis)
            _increment_budget(hypothesis)

            report_path = REPORTS_DIR / f"{datetime.now(UTC).strftime('%Y%m%d')}_{strategy_name}.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            content = (
                f"# Research Hypothesis: {strategy_name}\n\n"
                f"**Date:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}\n\n"
                f"## Proposed Parameters\n"
                f"```json\n{json.dumps(hypothesis.get('params', {}), indent=2)}\n```\n\n"
                f"## Expected Improvement\n"
                f"- **Sharpe:** {hypothesis.get('expected_sharpe_improvement', 0):.3f}\n"
                f"- **Rationale:** {hypothesis.get('rationale', 'N/A')}\n\n"
                f"## Status\n"
                f"- [ ] Pending Review\n"
                f"- [ ] Accepted\n"
                f"- [ ] Rejected\n"
            )
            report_path.write_text(content)
            logger.info("Research hypothesis saved: %s", report_path)

    await agent.on_stop()
    return hypotheses


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_research_scan())
