import pytest

from src.agents.strategy_gen import (
    ATRStrategy,
    BollingerBandsStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    RSIStrategy,
)


class TestMomentumStrategy:
    @pytest.mark.asyncio
    async def test_long_signal(self):
        s = MomentumStrategy(short_window=3, long_window=10, threshold=0.01)
        prices = [100.0] * 9 + [105.0, 106.0, 107.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "long"
        assert 0 < result["confidence"] <= 0.95

    @pytest.mark.asyncio
    async def test_short_signal(self):
        s = MomentumStrategy(short_window=3, long_window=10, threshold=0.01)
        prices = [100.0] * 9 + [95.0, 94.0, 93.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_no_signal_below_threshold(self):
        s = MomentumStrategy(short_window=3, long_window=10, threshold=0.05)
        prices = [100.0] * 13
        result = await s.evaluate("TEST", prices)
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        s = MomentumStrategy(long_window=20)
        result = await s.evaluate("TEST", [100.0] * 10)
        assert result is None


class TestMeanReversionStrategy:
    @pytest.mark.asyncio
    async def test_long_signal(self):
        s = MeanReversionStrategy(window=10, entry_z=1.5)
        prices = [100.0] * 10 + [95.0, 94.0, 93.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "long"

    @pytest.mark.asyncio
    async def test_short_signal(self):
        s = MeanReversionStrategy(window=10, entry_z=1.5)
        prices = [100.0] * 10 + [107.0, 108.0, 109.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_no_signal_within_bounds(self):
        s = MeanReversionStrategy(window=10, entry_z=3.0)
        prices = [100.0] * 13
        result = await s.evaluate("TEST", prices)
        assert result is None

    @pytest.mark.asyncio
    async def test_features_include_z_score(self):
        s = MeanReversionStrategy(window=10, entry_z=1.5)
        prices = [100.0] * 10 + [93.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert "z_score" in result["features"]
        assert "mean" in result["features"]
        assert "std" in result["features"]


class TestATRStrategy:
    @pytest.mark.asyncio
    async def test_long_signal(self):
        s = ATRStrategy(window=5, multiplier=2.0, threshold=0.005)
        prices = [100.0, 101.0, 100.5, 102.0, 101.0, 110.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "long"
        assert "atr" in result["features"]

    @pytest.mark.asyncio
    async def test_short_signal(self):
        s = ATRStrategy(window=5, multiplier=2.0, threshold=0.005)
        prices = [100.0, 99.0, 100.5, 98.0, 99.0, 90.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_no_signal_small_move(self):
        s = ATRStrategy(window=5, multiplier=3.0, threshold=0.05)
        prices = [100.0] * 10
        result = await s.evaluate("TEST", prices)
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        s = ATRStrategy(window=14)
        result = await s.evaluate("TEST", [100.0] * 5)
        assert result is None


class TestBollingerBandsStrategy:
    @pytest.mark.asyncio
    async def test_long_signal_below_lower(self):
        s = BollingerBandsStrategy(window=10, num_std=1.5)
        prices = [100.0] * 10 + [80.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "long"
        assert "upper" in result["features"]
        assert "lower" in result["features"]

    @pytest.mark.asyncio
    async def test_short_signal_above_upper(self):
        s = BollingerBandsStrategy(window=10, num_std=1.5)
        prices = [100.0] * 10 + [120.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_no_signal_inside_bands(self):
        s = BollingerBandsStrategy(window=10, num_std=3.0)
        prices = [100.0] * 11
        result = await s.evaluate("TEST", prices)
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        s = BollingerBandsStrategy(window=20)
        result = await s.evaluate("TEST", [100.0] * 10)
        assert result is None


class TestRSIStrategy:
    @pytest.mark.asyncio
    async def test_oversold_long_signal(self):
        s = RSIStrategy(window=5, oversold=30.0, overbought=70.0)
        prices = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "long"
        assert "rsi" in result["features"]

    @pytest.mark.asyncio
    async def test_overbought_short_signal(self):
        s = RSIStrategy(window=5, oversold=30.0, overbought=70.0)
        prices = [100.0, 101.5, 103.0, 104.5, 106.0, 107.5]
        result = await s.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_no_signal_neutral_rsi(self):
        s = RSIStrategy(window=5, oversold=30.0, overbought=70.0)
        prices = [100.0] * 5 + [100.5, 99.5, 101.0, 99.0, 100.0]
        result = await s.evaluate("TEST", prices)
        assert result is None or 30 < result["features"]["rsi"] < 70

    @pytest.mark.asyncio
    async def test_rsi_calculation_range(self):
        s = RSIStrategy(window=5)
        prices = [100.0] * 5 + [95.0, 94.0, 93.0, 92.0, 91.0]
        result = await s.evaluate("TEST", prices)
        if result is not None:
            rsi = result["features"]["rsi"]
            assert 0 <= rsi <= 100

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        s = RSIStrategy(window=14)
        result = await s.evaluate("TEST", [100.0] * 5)
        assert result is None
