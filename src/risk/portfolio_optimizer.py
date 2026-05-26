"""
Institutional Portfolio Optimizer
=================================
Allocates capital across *strategy books* using four regimes:

1. **Risk Parity** — equalise each strategy's contribution to total portfolio risk.
2. **Minimum Variance** — minimise total portfolio variance (most defensive).
3. **Maximum Sharpe** — maximise the ex-ante Sharpe ratio.
4. **Equal Weight** — simple 1/N fallback.

Inputs
------
A dict of ``{strategy_name: np.ndarray}`` where each array is a time-series of
periodic returns (e.g. daily or per-trade P&L as a fraction of allocated capital).

Features
--------
* Ledoit-Wolf covariance shrinkage for numerical stability.
* Configurable per-strategy weight floor / ceiling.
* Graceful degradation: single strategy → 100 %; insufficient data → equal weight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger("risk.portfolio_optimizer")

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class OptimizationResult:
    """Output of a portfolio optimisation run."""
    weights: dict[str, float]
    regime_used: str
    expected_return: float = 0.0
    expected_vol: float = 0.0
    sharpe: float = 0.0
    cov_condition_number: float = 0.0
    shrinkage_intensity: float = 0.0
    converged: bool = True


# ---------------------------------------------------------------------------
# Ledoit-Wolf shrinkage (simplified analytical estimator)
# ---------------------------------------------------------------------------

def _ledoit_wolf_shrinkage(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Compute the Ledoit-Wolf shrinkage estimator for the covariance matrix.

    Parameters
    ----------
    returns : (T, N) array of centred returns.

    Returns
    -------
    cov_shrunk : (N, N) shrunk covariance matrix
    shrinkage  : float, the optimal shrinkage intensity in [0, 1]
    """
    T, N = returns.shape
    if T < 2 or N < 1:
        return np.eye(N), 1.0

    sample_cov = np.cov(returns, rowvar=False, bias=False)

    # np.cov returns a scalar for N=1; reshape to (1,1)
    if sample_cov.ndim == 0:
        sample_cov = sample_cov.reshape(1, 1)

    # Shrinkage target: diagonal matrix of variances (constant-correlation target)
    target = np.diag(np.diag(sample_cov))

    # Frobenius norm components for optimal shrinkage intensity
    X = returns - returns.mean(axis=0)
    S = X.T @ X / T

    # Compute the squared Frobenius norm of S - target
    delta = S - target
    sum_sq_delta = np.sum(delta ** 2)

    # Estimate the sum of variances of sample covariance entries
    sum_sq_pi = 0.0
    for t in range(T):
        x_t = X[t:t+1, :]  # (1, N)
        m_t = x_t.T @ x_t - S
        sum_sq_pi += np.sum(m_t ** 2)
    sum_sq_pi /= T ** 2

    # Optimal shrinkage intensity (clamped to [0, 1])
    if sum_sq_delta == 0:
        shrinkage = 1.0
    else:
        shrinkage = max(0.0, min(1.0, sum_sq_pi / sum_sq_delta))

    cov_shrunk = shrinkage * target + (1.0 - shrinkage) * sample_cov
    return cov_shrunk, shrinkage


# ---------------------------------------------------------------------------
# Core optimizer
# ---------------------------------------------------------------------------

class InstitutionalPortfolioOptimizer:
    """
    Multi-regime portfolio optimizer.

    Parameters
    ----------
    regime : Which objective function to use.
    min_weight : Floor for every strategy weight.
    max_weight : Ceiling for every strategy weight.
    risk_free_rate : Annualised risk-free rate (used only for max_sharpe).
    min_history : Minimum number of return observations before optimising.
    """

    VALID_REGIMES = ("risk_parity", "min_variance", "max_sharpe", "equal_weight")

    def __init__(
        self,
        regime: Literal["risk_parity", "min_variance", "max_sharpe", "equal_weight"] = "risk_parity",
        min_weight: float = 0.05,
        max_weight: float = 0.40,
        risk_free_rate: float = 0.06,
        min_history: int = 20,
    ):
        if regime not in self.VALID_REGIMES:
            raise ValueError(f"Invalid regime '{regime}'. Choose from {self.VALID_REGIMES}")
        self.regime = regime
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.risk_free_rate = risk_free_rate
        self.min_history = min_history

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, strategy_returns: dict[str, np.ndarray]) -> OptimizationResult:
        """
        Run the optimizer on a dict of strategy return series.

        Parameters
        ----------
        strategy_returns : ``{name: 1-D array of periodic returns}``

        Returns
        -------
        OptimizationResult
        """
        names = list(strategy_returns.keys())
        n = len(names)

        # --- Edge cases: graceful degradation ---
        if n == 0:
            logger.warning("No strategies provided — returning empty weights")
            return OptimizationResult(weights={}, regime_used="empty")

        if n == 1:
            logger.info("Single strategy '%s' — assigning 100%% weight", names[0])
            return OptimizationResult(
                weights={names[0]: 1.0},
                regime_used="single_strategy",
            )

        # Trim all series to the shortest common length
        min_len = min(len(v) for v in strategy_returns.values())
        if min_len < self.min_history:
            logger.warning(
                "Insufficient history (%d < %d) — falling back to equal weight",
                min_len, self.min_history,
            )
            eq = 1.0 / n
            return OptimizationResult(
                weights={name: eq for name in names},
                regime_used="equal_weight_fallback",
            )

        # Build (T, N) returns matrix
        returns_matrix = np.column_stack([
            strategy_returns[name][-min_len:] for name in names
        ])

        # Shrunk covariance
        cov, shrinkage = _ledoit_wolf_shrinkage(returns_matrix)
        cond = float(np.linalg.cond(cov))

        # Mean returns
        mu = returns_matrix.mean(axis=0)

        # Dispatch to the chosen regime
        if self.regime == "equal_weight":
            weights = self._equal_weight(n)
            converged = True
        elif self.regime == "min_variance":
            weights, converged = self._min_variance(cov, n)
        elif self.regime == "max_sharpe":
            weights, converged = self._max_sharpe(mu, cov, n)
        elif self.regime == "risk_parity":
            weights, converged = self._risk_parity(cov, n)
        else:
            weights = self._equal_weight(n)
            converged = True

        # Compute portfolio metrics
        port_ret = float(mu @ weights)
        port_vol = float(np.sqrt(weights @ cov @ weights))
        port_sharpe = (port_ret - self.risk_free_rate / 252) / port_vol if port_vol > 1e-12 else 0.0

        result = OptimizationResult(
            weights=dict(zip(names, [float(w) for w in weights])),
            regime_used=self.regime,
            expected_return=port_ret,
            expected_vol=port_vol,
            sharpe=port_sharpe,
            cov_condition_number=cond,
            shrinkage_intensity=shrinkage,
            converged=converged,
        )

        logger.info(
            "Optimized [%s]: %s | E[r]=%.4f vol=%.4f SR=%.2f shrink=%.2f cond=%.1f",
            result.regime_used,
            {k: f"{v:.1%}" for k, v in result.weights.items()},
            result.expected_return,
            result.expected_vol,
            result.sharpe,
            result.shrinkage_intensity,
            result.cov_condition_number,
        )
        return result

    # ------------------------------------------------------------------
    # Regime implementations
    # ------------------------------------------------------------------

    def _equal_weight(self, n: int) -> np.ndarray:
        return np.full(n, 1.0 / n)

    def _min_variance(self, cov: np.ndarray, n: int) -> tuple[np.ndarray, bool]:
        """Minimise w' Σ w subject to Σw = 1 and bounds."""

        def objective(w):
            return w @ cov @ w

        return self._solve(objective, n)

    def _max_sharpe(self, mu: np.ndarray, cov: np.ndarray, n: int) -> tuple[np.ndarray, bool]:
        """Maximise (w'μ - rf) / sqrt(w'Σw)."""
        rf_daily = self.risk_free_rate / 252

        def objective(w):
            port_ret = mu @ w
            port_vol = np.sqrt(w @ cov @ w)
            if port_vol < 1e-12:
                return 1e6
            # Minimise negative Sharpe
            return -(port_ret - rf_daily) / port_vol

        return self._solve(objective, n)

    def _risk_parity(self, cov: np.ndarray, n: int) -> tuple[np.ndarray, bool]:
        """Equalise marginal risk contribution across strategies."""
        target_risk = np.full(n, 1.0 / n)

        def objective(w):
            port_var = w @ cov @ w
            if port_var < 1e-16:
                return 1e6
            marginal = cov @ w
            risk_contrib = w * marginal / port_var
            return float(np.sum((risk_contrib - target_risk) ** 2))

        return self._solve(objective, n)

    # ------------------------------------------------------------------
    # Common solver wrapper
    # ------------------------------------------------------------------

    def _solve(self, objective, n: int) -> tuple[np.ndarray, bool]:
        """Run SLSQP with weight constraints."""
        x0 = np.full(n, 1.0 / n)
        bounds = [(self.min_weight, self.max_weight)] * n
        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

        try:
            res = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-12, "disp": False},
            )
            if res.success:
                return res.x, True
            else:
                logger.warning("Optimizer did not converge: %s — using last iterate", res.message)
                # Still return normalised weights from last iterate
                w = np.clip(res.x, self.min_weight, self.max_weight)
                w /= w.sum()
                return w, False
        except Exception as e:
            logger.error("Optimization failed: %s — falling back to equal weight", e)
            return np.full(n, 1.0 / n), False
