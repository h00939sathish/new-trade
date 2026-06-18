import numpy as np
import pytest
from src.strategies.ml_regime import SKLEARN_AVAILABLE, MLRegimeStrategy


@pytest.mark.asyncio
async def test_ml_regime_insufficient_data():
    strategy = MLRegimeStrategy(lookback_window=100)
    # Give it less than 100 prices
    prices = [100.0 + i for i in range(50)]
    result = await strategy.evaluate("RELIANCE", prices)
    assert result is None
    assert not strategy.is_trained


@pytest.mark.asyncio
async def test_ml_regime_training_and_prediction():
    if not SKLEARN_AVAILABLE:
        pytest.skip("scikit-learn not installed")

    strategy = MLRegimeStrategy(lookback_window=100, prediction_horizon=5)

    # Create an oscillating trend so the model sees both UP and DOWN
    prices = [100.0 + np.sin(i * 0.5) * 10 for i in range(120)]

    result = await strategy.evaluate("RELIANCE", prices)

    assert strategy.is_trained
    # Since it's a perfect uptrend, the model should predict 'long'
    assert result is not None
    assert result["direction"] in ["long", "short"]
