import logging
import random
from dataclasses import dataclass

import numpy as np

from src.backtest.engine import BacktestResult

logger = logging.getLogger("validation.monte_carlo")


@dataclass
class MonteCarloResult:
    passed: bool
    probability_of_loss: float
    sharpe_ci_lower: float
    sharpe_ci_upper: float
    median_sharpe: float
    var_95: float
    avg_max_drawdown: float
    n_simulations: int


class MonteCarloValidator:
    def __init__(self, n_simulations: int = 1000, confidence_level: float = 0.95):
        self.n_simulations = n_simulations
        self.confidence_level = confidence_level

    def run(self, result: BacktestResult, trade_pnls: list[float]) -> MonteCarloResult:
        if not trade_pnls:
            return MonteCarloResult(
                passed=False,
                probability_of_loss=1.0,
                sharpe_ci_lower=0.0,
                sharpe_ci_upper=0.0,
                median_sharpe=0.0,
                var_95=0.0,
                avg_max_drawdown=0.0,
                n_simulations=self.n_simulations,
            )

        n_trades = len(trade_pnls)
        sharpe_values = []
        max_drawdowns = []
        final_pnls = []

        for _ in range(self.n_simulations):
            resampled = [random.choice(trade_pnls) for _ in range(n_trades)]
            sim_sharpe = self._compute_sharpe(resampled)
            sharpe_values.append(sim_sharpe)

            cumulative = np.cumsum(resampled)
            final_pnls.append(cumulative[-1])

            peak = np.maximum.accumulate(cumulative)
            dd = np.max(peak - cumulative)
            max_drawdowns.append(dd)

        sharpe_values = np.array(sharpe_values)
        final_pnls = np.array(final_pnls)

        lower_tail = (1.0 - self.confidence_level) / 2.0
        upper_tail = 1.0 - lower_tail

        median_sharpe = float(np.median(sharpe_values))
        sharpe_ci_lower = float(np.percentile(sharpe_values, lower_tail * 100))
        sharpe_ci_upper = float(np.percentile(sharpe_values, upper_tail * 100))
        probability_of_loss = float(np.mean(final_pnls < 0))
        var_95 = float(np.percentile(final_pnls, 5.0))
        avg_max_drawdown = float(np.mean(max_drawdowns))

        passed = median_sharpe >= 0.8 and probability_of_loss < 0.60

        return MonteCarloResult(
            passed=passed,
            probability_of_loss=probability_of_loss,
            sharpe_ci_lower=sharpe_ci_lower,
            sharpe_ci_upper=sharpe_ci_upper,
            median_sharpe=median_sharpe,
            var_95=var_95,
            avg_max_drawdown=avg_max_drawdown,
            n_simulations=self.n_simulations,
        )

    def _compute_sharpe(self, pnls: list[float]) -> float:
        pnl_array = np.array(pnls)
        if len(pnl_array) < 2 or np.std(pnl_array) == 0:
            return 0.0
        mean_pnl = np.mean(pnl_array)
        std_pnl = np.std(pnl_array, ddof=1)
        if std_pnl == 0:
            return 0.0
        return float((mean_pnl / std_pnl) * np.sqrt(252))
