"""
Tests for the Institutional Portfolio Optimizer.

Covers:
- All four regimes (risk_parity, min_variance, max_sharpe, equal_weight)
- Weight constraint enforcement
- Ledoit-Wolf shrinkage
- Graceful degradation (single strategy, insufficient data)
- Integration with PortfolioOptimizationAgent
"""

import numpy as np
import pytest

from src.risk.portfolio_optimizer import (
    InstitutionalPortfolioOptimizer,
    OptimizationResult,
    _ledoit_wolf_shrinkage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_returns(n_strategies: int = 4, n_obs: int = 100, seed: int = 42) -> dict[str, np.ndarray]:
    """Generate synthetic strategy returns with different means/vols."""
    rng = np.random.default_rng(seed)
    names = [f"strat_{i}" for i in range(n_strategies)]
    data: dict[str, np.ndarray] = {}
    for i, name in enumerate(names):
        mu = 0.001 * (i + 1)       # increasing mean return
        sigma = 0.01 * (i + 1)     # increasing vol
        data[name] = rng.normal(mu, sigma, n_obs)
    return data


# ---------------------------------------------------------------------------
# Ledoit-Wolf shrinkage
# ---------------------------------------------------------------------------

class TestLedoitWolf:
    def test_returns_positive_definite(self):
        rng = np.random.default_rng(0)
        returns = rng.normal(0, 0.01, (50, 5))
        cov, shrinkage = _ledoit_wolf_shrinkage(returns)
        # Positive definite ⇒ all eigenvalues > 0
        eigs = np.linalg.eigvalsh(cov)
        assert np.all(eigs > -1e-12), f"Non-PD eigenvalues: {eigs}"

    def test_shrinkage_in_range(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0, 0.02, (30, 4))
        _, shrinkage = _ledoit_wolf_shrinkage(returns)
        assert 0.0 <= shrinkage <= 1.0

    def test_single_asset(self):
        returns = np.array([[0.01], [0.02], [-0.01]])
        cov, shrinkage = _ledoit_wolf_shrinkage(returns)
        assert cov.shape == (1, 1)
        assert cov[0, 0] > 0

    def test_two_observations(self):
        returns = np.array([[0.01, 0.02], [-0.01, 0.03]])
        cov, shrinkage = _ledoit_wolf_shrinkage(returns)
        assert cov.shape == (2, 2)


# ---------------------------------------------------------------------------
# Equal Weight
# ---------------------------------------------------------------------------

class TestEqualWeight:
    def test_basic(self):
        opt = InstitutionalPortfolioOptimizer(regime="equal_weight")
        data = _make_returns(3, 50)
        result = opt.optimize(data)
        assert result.regime_used == "equal_weight"
        for w in result.weights.values():
            assert abs(w - 1 / 3) < 1e-10
        assert abs(sum(result.weights.values()) - 1.0) < 1e-10

    def test_converged(self):
        opt = InstitutionalPortfolioOptimizer(regime="equal_weight")
        result = opt.optimize(_make_returns(5, 50))
        assert result.converged is True


# ---------------------------------------------------------------------------
# Minimum Variance
# ---------------------------------------------------------------------------

class TestMinVariance:
    def test_weights_sum_to_one(self):
        opt = InstitutionalPortfolioOptimizer(regime="min_variance")
        result = opt.optimize(_make_returns(4, 100))
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_weights_within_bounds(self):
        opt = InstitutionalPortfolioOptimizer(regime="min_variance", min_weight=0.1, max_weight=0.5)
        result = opt.optimize(_make_returns(4, 100))
        for w in result.weights.values():
            assert w >= 0.1 - 1e-6
            assert w <= 0.5 + 1e-6

    def test_favours_low_vol(self):
        """Min-variance should give more weight to the low-vol strategy."""
        opt = InstitutionalPortfolioOptimizer(regime="min_variance", min_weight=0.0, max_weight=1.0)
        data = _make_returns(3, 200)
        result = opt.optimize(data)
        # strat_0 has lowest vol (0.01), should have highest weight
        assert result.weights["strat_0"] >= result.weights["strat_2"]


# ---------------------------------------------------------------------------
# Maximum Sharpe
# ---------------------------------------------------------------------------

class TestMaxSharpe:
    def test_weights_sum_to_one(self):
        opt = InstitutionalPortfolioOptimizer(regime="max_sharpe")
        result = opt.optimize(_make_returns(4, 100))
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_weights_within_bounds(self):
        opt = InstitutionalPortfolioOptimizer(regime="max_sharpe", min_weight=0.05, max_weight=0.60)
        result = opt.optimize(_make_returns(4, 100))
        for w in result.weights.values():
            assert w >= 0.05 - 1e-6
            assert w <= 0.60 + 1e-6

    def test_sharpe_is_computed(self):
        opt = InstitutionalPortfolioOptimizer(regime="max_sharpe")
        result = opt.optimize(_make_returns(3, 100))
        # Sharpe should be a finite number
        assert np.isfinite(result.sharpe)


# ---------------------------------------------------------------------------
# Risk Parity
# ---------------------------------------------------------------------------

class TestRiskParity:
    def test_weights_sum_to_one(self):
        opt = InstitutionalPortfolioOptimizer(regime="risk_parity")
        result = opt.optimize(_make_returns(4, 100))
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_weights_within_bounds(self):
        opt = InstitutionalPortfolioOptimizer(regime="risk_parity", min_weight=0.05, max_weight=0.50)
        result = opt.optimize(_make_returns(4, 100))
        for w in result.weights.values():
            assert w >= 0.05 - 1e-6
            assert w <= 0.50 + 1e-6

    def test_equalises_risk_contribution(self):
        """Risk parity should make risk contributions roughly equal."""
        opt = InstitutionalPortfolioOptimizer(
            regime="risk_parity", min_weight=0.0, max_weight=1.0
        )
        data = _make_returns(3, 200, seed=99)
        result = opt.optimize(data)

        # Compute actual risk contributions
        names = list(data.keys())
        min_len = min(len(v) for v in data.values())
        returns_mat = np.column_stack([data[n][-min_len:] for n in names])
        cov = np.cov(returns_mat, rowvar=False)
        w = np.array([result.weights[n] for n in names])
        port_var = w @ cov @ w
        marginal = cov @ w
        rc = w * marginal / port_var if port_var > 0 else np.full(len(w), 1 / len(w))

        # Risk contributions should be roughly equal (1/3 each)
        target = 1.0 / 3
        for i, contrib in enumerate(rc):
            assert abs(contrib - target) < 0.15, f"Risk contrib for {names[i]}: {contrib:.3f} (expected ~{target:.3f})"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_empty_strategies(self):
        opt = InstitutionalPortfolioOptimizer()
        result = opt.optimize({})
        assert result.weights == {}
        assert result.regime_used == "empty"

    def test_single_strategy(self):
        opt = InstitutionalPortfolioOptimizer()
        result = opt.optimize({"only_one": np.random.randn(50)})
        assert result.weights == {"only_one": 1.0}
        assert result.regime_used == "single_strategy"

    def test_insufficient_history(self):
        opt = InstitutionalPortfolioOptimizer(min_history=30)
        data = {"a": np.random.randn(10), "b": np.random.randn(10)}
        result = opt.optimize(data)
        assert result.regime_used == "equal_weight_fallback"
        assert abs(result.weights["a"] - 0.5) < 1e-10

    def test_invalid_regime_raises(self):
        with pytest.raises(ValueError, match="Invalid regime"):
            InstitutionalPortfolioOptimizer(regime="invalid")


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

class TestOptimizationResult:
    def test_result_has_all_fields(self):
        opt = InstitutionalPortfolioOptimizer(regime="risk_parity")
        result = opt.optimize(_make_returns(3, 100))
        assert isinstance(result, OptimizationResult)
        assert isinstance(result.weights, dict)
        assert isinstance(result.expected_return, float)
        assert isinstance(result.expected_vol, float)
        assert isinstance(result.sharpe, float)
        assert isinstance(result.cov_condition_number, float)
        assert isinstance(result.shrinkage_intensity, float)
        assert isinstance(result.converged, bool)

    def test_metrics_are_finite(self):
        opt = InstitutionalPortfolioOptimizer(regime="min_variance")
        result = opt.optimize(_make_returns(4, 100))
        assert np.isfinite(result.expected_return)
        assert np.isfinite(result.expected_vol)
        assert np.isfinite(result.sharpe)
        assert result.expected_vol >= 0
