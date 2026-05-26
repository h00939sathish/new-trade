import pytest

from src.strategies.vol_breakout import VolatilityBreakoutStrategy


@pytest.mark.asyncio
async def test_vol_breakout_insufficient_data():
    strategy = VolatilityBreakoutStrategy(window=10)
    prices = [100.0] * 5
    highs = [105.0] * 5
    lows = [95.0] * 5
    result = await strategy.evaluate("RELIANCE", prices, highs=highs, lows=lows)
    assert result is None

@pytest.mark.asyncio
async def test_vol_breakout_long_signal():
    strategy = VolatilityBreakoutStrategy(window=5)
    prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]
    highs = [105.0, 106.0, 107.0, 108.0, 109.0, 109.5, 111.0]
    lows = [95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 105.0]

    result = await strategy.evaluate("RELIANCE", prices, highs=highs, lows=lows)

    assert result is not None
    assert result["direction"] == "long"
    assert result["features"]["highest_high"] == 109.5
