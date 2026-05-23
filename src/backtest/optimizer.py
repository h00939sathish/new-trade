import itertools
import logging
from dataclasses import dataclass, field
from typing import Any

from src.agents.strategy_gen import Strategy
from src.backtest.engine import BacktestEngine, BacktestResult

logger = logging.getLogger("backtest.optimizer")


@dataclass
class OptimizationResult:
    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float = 0.0
    best_result: BacktestResult | None = None
    results: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Best params: {self.best_params}",
            f"Best score: {self.best_score:.4f}",
            f"Results evaluated: {len(self.results)}",
        ]
        if self.best_result:
            r = self.best_result
            lines.append(f"Sharpe: {r.sharpe_ratio:.3f}, Win Rate: {r.win_rate:.1%}, PnL: {r.total_pnl:.2f}")
        return "\n".join(lines)


async def grid_search(
    strategy_class: type[Strategy],
    param_grid: dict[str, list[Any]],
    ticks: list[dict[str, Any]],
    initial_capital: float = 1_000_000.0,
    metric: str = "sharpe_ratio",
    top_n: int = 1,
) -> OptimizationResult:
    keys = list(param_grid.keys())
    value_lists = list(param_grid.values())
    results: list[dict[str, Any]] = []
    best_score = float("-inf")
    best_params = {}
    best_result: BacktestResult | None = None

    total = 1
    for v in value_lists:
        total *= len(v)

    for i, combo in enumerate(itertools.product(*value_lists)):
        params = dict(zip(keys, combo))
        strategy = strategy_class(**params)
        engine = BacktestEngine(
            strategies=[strategy],
            initial_capital=initial_capital,
        )
        try:
            result = await engine.run(ticks)
            score = getattr(result, metric, 0.0)
            if score is None:
                score = 0.0
            results.append({"params": params, metric: score, "result": result})
            if score > best_score:
                best_score = score
                best_params = params
                best_result = result
        except Exception as e:
            logger.warning("Params %s failed: %s", params, e)

        if (i + 1) % max(1, total // 10) == 0:
            logger.info("Grid search: %d/%d (%.0f%%)", i + 1, total, (i + 1) / total * 100)

    results.sort(key=lambda r: r.get(metric, 0.0), reverse=True)

    return OptimizationResult(
        best_params=best_params,
        best_score=best_score,
        best_result=best_result,
        results=results[:top_n],
    )
