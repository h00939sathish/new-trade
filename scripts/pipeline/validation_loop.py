"""
LOOP 2 — Validation Loop
=========================
Trigger:  New hypothesis accepted by human
Action:
  Stage 1: Backtest   -> pass if Sharpe >= 1.2, PF >= 1.3, DD <= 10%
  Stage 2: Walk Fwd   -> pass if OOS Sharpe >= 1.0
  Stage 3: Monte Carlo -> pass if 95%ile Sharpe >= 0.8
  Stage 4: Paper Trade -> 30-day live simulation with realistic slippage
  Failure at any stage -> reject with report
Stop:     All 4 stages pass -> Champion Challenge queue
Verify:   reports/validation/{strategy}_{date}.json with stage-by-stage results
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.validation_loop")

REPORTS_DIR = Path("reports/validation")
DATA_CACHE = Path("data/parquet")


async def run_validation(
    strategy_name: str,
    params: dict[str, Any],
    config_path: str | None = None,
) -> dict[str, Any]:
    """Run the full 4-stage validation pipeline for a strategy hypothesis."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    from src.validation.orchestrator import ValidationPipeline

    pipeline = ValidationPipeline(
        config_path=config_path or "config/strategies.yaml",
        data_provider=None,
    )

    from src.config.strategy_config import STRATEGY_REGISTRY

    strategy_class = STRATEGY_REGISTRY.get(strategy_name)
    if not strategy_class:
        logger.error("Unknown strategy: %s", strategy_name)
        return {"strategy": strategy_name, "passed": False, "error": "Unknown strategy"}

    report = await pipeline.run(
        strategy_name=strategy_name,
        strategy_class=strategy_class,
        params=params,
    )

    report_dict = report.to_dict() if hasattr(report, "to_dict") else report.__dict__
    report_path = REPORTS_DIR / f"{strategy_name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report_dict, indent=2, default=str))
    logger.info("Validation report saved: %s", report_path)

    if report.passed:
        logger.info(
            "VALIDATION PASSED: %s (score=%.2f)", strategy_name, getattr(report, "overall_score", 0)
        )
    else:
        logger.warning("VALIDATION FAILED: %s", strategy_name)

    return report_dict


def validate_from_hypothesis(hypothesis_path: str) -> dict[str, Any]:
    """Load a research hypothesis and run validation."""
    path = Path(hypothesis_path)
    if not path.exists():
        logger.error("Hypothesis file not found: %s", hypothesis_path)
        return {"error": "File not found"}

    import re

    content = path.read_text()
    name_match = re.search(r"# Research Hypothesis: (\w+)", content)
    strategy_name = name_match.group(1) if name_match else "unknown"

    json_match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
    params = json.loads(json_match.group(1)) if json_match else {}

    import asyncio

    return asyncio.run(run_validation(strategy_name, params))


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        result = validate_from_hypothesis(sys.argv[1])
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage: python -m scripts.pipeline.validation_loop <hypothesis_md_path>")
        print("Example: python -m scripts.pipeline.validation_loop reports/research/20260621_momentum.md")
