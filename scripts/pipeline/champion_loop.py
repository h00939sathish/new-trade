"""
LOOP 3 — Champion Challenger Loop
===================================
Trigger:  New candidate passes Validation Loop
Action:
  1. Load champion config for strategy category
  2. Paper-trade candidate vs champion in parallel (shadow mode)
  3. Compare: Sharpe, Sortino, Expectancy, PF, DD
  4. Candidate > Champion -> promote | else -> reject
Stop:     Decision made (promote or reject)
Verify:   reports/attribution/challenge_log.csv with all comparisons
"""

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.champion_loop")

CHALLENGE_LOG = Path("reports/attribution/challenge_log.csv")


def categorize_strategy(strategy_name: str) -> str:
    category_map = {
        "momentum": "momentum",
        "tsmom": "momentum",
        "sideways_reversion": "mean_reversion",
        "vwap_reversion": "mean_reversion",
        "mean_reversion": "mean_reversion",
        "orb": "breakout",
        "vol_compression": "volatility",
        "vol_breakout": "breakout",
        "atr_breakout": "breakout",
        "opening_range_breakout": "breakout",
        "stat_arb": "stat_arb",
        "bollinger": "volatility",
        "rsi": "mean_reversion",
        "macd": "momentum",
    }
    return category_map.get(strategy_name, "other")


async def run_champion_challenge(
    strategy_name: str,
    candidate_params: dict[str, Any],
    backtest_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a champion-challenger comparison for a strategy candidate."""
    from src.backtest.engine import BacktestEngine
    from src.challenge import ChallengeOrchestrator
    from src.champion import ChampionRegistry
    from src.config.strategy_config import STRATEGY_REGISTRY

    category = categorize_strategy(strategy_name)
    registry = ChampionRegistry()

    champion = registry.get_champion(category)
    strategy_class = STRATEGY_REGISTRY.get(strategy_name)
    if not strategy_class:
        return {"error": f"Unknown strategy: {strategy_name}"}

    engine = BacktestEngine(initial_capital=1_000_000.0)
    engine._strategy_gen.register_strategy(strategy_class(**candidate_params))

    ticks = backtest_data or []
    if not ticks:
        from src.connectors.backtest_provider import generate_synthetic_ticks
        ticks = generate_synthetic_ticks()

    candidate_result = await engine.run(ticks)
    candidate_metrics = {
        "sharpe": candidate_result.sharpe_ratio,
        "profit_factor": candidate_result.profit_factor,
        "total_pnl": candidate_result.total_pnl,
        "max_drawdown": candidate_result.max_drawdown,
        "win_rate": candidate_result.win_rate,
        "total_trades": candidate_result.total_trades,
    }

    if not champion:
        registry.set_champion(category, strategy_name, candidate_params, candidate_metrics)
        logger.info("No champion for %s — promoting candidate as champion", category)
        return {
            "category": category,
            "champion": None,
            "challenger": strategy_name,
            "challenger_won": True,
            "action": "promoted_as_first_champion",
            "candidate_metrics": candidate_metrics,
        }

    orchestrator = ChallengeOrchestrator(registry, engine, None)
    result = orchestrator.run_challenge(category, strategy_name, candidate_params, ticks)

    outcome = {
        "timestamp": datetime.now(UTC).isoformat(),
        "category": category,
        "champion_name": champion.get("strategy_name"),
        "challenger_name": strategy_name,
        "challenger_won": result.challenger_won if hasattr(result, "challenger_won") else False,
        "champion_metrics": champion.get("metrics", {}),
        "challenger_metrics": candidate_metrics,
    }

    CHALLENGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    file_exists = CHALLENGE_LOG.exists()
    with CHALLENGE_LOG.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(outcome.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(outcome)

    if outcome["challenger_won"]:
        registry.promote(category, {
            "strategy_name": strategy_name,
            "params": candidate_params,
            "metrics": candidate_metrics,
            "promoted_date": datetime.now(UTC).isoformat(),
            "category": category,
        })
        logger.info("CHAMPION PROMOTED: %s replaces %s in %s", strategy_name, champion.get("strategy_name"), category)
    else:
        logger.info("CHALLENGER REJECTED: %s did not beat champion %s in %s", strategy_name, champion.get("strategy_name"), category)

    return outcome


if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) >= 3:
        result = asyncio.run(run_champion_challenge(sys.argv[1], json.loads(sys.argv[2])))
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage: python -m scripts.pipeline.champion_loop <strategy_name> '<params_json>'")
