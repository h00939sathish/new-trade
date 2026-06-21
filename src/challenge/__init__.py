import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChallengeResult:
    category: str
    champion_name: str
    challenger_name: str
    champion_metrics: dict[str, float] = field(default_factory=dict)
    challenger_metrics: dict[str, float] = field(default_factory=dict)
    challenger_won: bool = False
    improvement_pct: dict[str, float] = field(default_factory=dict)
    recommendation: str = "reject"


class ChallengeOrchestrator:
    def __init__(self, champion_registry, backtest_engine, attribution_tracker):
        self._champion_registry = champion_registry
        self._backtest_engine = backtest_engine
        self._attribution_tracker = attribution_tracker

    async def run_challenge(
        self,
        category: str,
        candidate_name: str,
        candidate_params: dict[str, Any],
        backtest_data: Any,
    ) -> ChallengeResult:
        champion = self._champion_registry.get_champion(category)
        champion_name = champion.get("strategy_name", "none") if champion else "none"
        champion_metrics = champion.get("metrics", {}) if champion else {}

        challenger_metrics = await self._backtest_engine.run(
            candidate_name, candidate_params, backtest_data
        )

        if not champion:
            result = ChallengeResult(
                category=category,
                champion_name="none",
                challenger_name=candidate_name,
                champion_metrics={},
                challenger_metrics=challenger_metrics,
                challenger_won=True,
                improvement_pct={},
                recommendation="promote",
            )
            logger.info(
                "No champion for '%s', promoting '%s' by default",
                category,
                candidate_name,
            )
            return result

        challenger_won = self.compare(champion_metrics, challenger_metrics)

        improvement_pct = {}
        for key in challenger_metrics:
            champ_val = champion_metrics.get(key, 0.0)
            if champ_val != 0:
                improvement_pct[key] = (
                    (challenger_metrics[key] - champ_val) / abs(champ_val) * 100
                )
            else:
                improvement_pct[key] = (
                    100.0 if challenger_metrics[key] != 0 else 0.0
                )

        recommendation = "promote" if challenger_won else "reject"

        if challenger_won:
            logger.info(
                "Challenger '%s' beats champion '%s' in '%s' — recommending promote",
                candidate_name,
                champion_name,
                category,
            )

        return ChallengeResult(
            category=category,
            champion_name=champion_name,
            challenger_name=candidate_name,
            champion_metrics=champion_metrics,
            challenger_metrics=challenger_metrics,
            challenger_won=challenger_won,
            improvement_pct=improvement_pct,
            recommendation=recommendation,
        )

    def compare(
        self,
        champion_metrics: dict[str, float],
        challenger_metrics: dict[str, float],
    ) -> bool:
        champ_sharpe = champion_metrics.get("sharpe", 0.0)
        champ_pf = champion_metrics.get("profit_factor", 0.0)
        champ_expectancy = champion_metrics.get("expectancy", 0.0)
        champ_win_rate = champion_metrics.get("win_rate", 0.0)
        champ_dd = champion_metrics.get("max_drawdown", 0.0)

        chal_sharpe = challenger_metrics.get("sharpe", 0.0)
        chal_pf = challenger_metrics.get("profit_factor", 0.0)
        chal_expectancy = challenger_metrics.get("expectancy", 0.0)
        chal_win_rate = challenger_metrics.get("win_rate", 0.0)
        chal_dd = challenger_metrics.get("max_drawdown", 0.0)

        if chal_dd > champ_dd * 1.5:
            logger.info(
                "Challenger drawdown (%.2f) > 1.5x champion drawdown (%.2f) — rejecting",
                chal_dd,
                champ_dd,
            )
            return False

        sharpe_improvement = chal_sharpe - champ_sharpe
        pf_improvement = chal_pf - champ_pf

        if sharpe_improvement >= 0.1 and pf_improvement >= 0.1:
            return True

        if sharpe_improvement >= 0.2:
            return True

        if (
            chal_sharpe > champ_sharpe
            and chal_expectancy > champ_expectancy
            and chal_win_rate > champ_win_rate
        ):
            return True

        return False


__all__ = ["ChallengeOrchestrator", "ChallengeResult"]
