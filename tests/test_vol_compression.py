import pytest
from src.strategies.volatility_compression import VolatilityCompressionStrategy

@pytest.mark.asyncio
async def test_vol_compression_insufficient_data():
    strategy = VolatilityCompressionStrategy()
    signal = await strategy.evaluate("RELIANCE", prices=[100.0] * 50, highs=[101.0]*50, lows=[99.0]*50)
    assert signal is None

@pytest.mark.asyncio
async def test_vol_compression_signal():
    strategy = VolatilityCompressionStrategy(bb_window=5, lookback=10, atr_window=3)
    
    # Create a history of wide BB and large ATR
    prices = [100.0, 110.0, 90.0, 105.0, 95.0, 108.0, 92.0, 100.0] * 3
    highs = [p + 5 for p in prices]
    lows = [p - 5 for p in prices]
    
    # Compress it, with contracting ATR
    spread = 4.0
    for i in range(10):
        prices.append(100.0)
        highs.append(100.0 + spread/2)
        lows.append(100.0 - spread/2)
        spread = max(0.5, spread - 0.5)
        
    # Breakout up
    prices.append(105.0)
    highs.append(106.0)
    lows.append(100.0)
    
    signal = await strategy.evaluate("RELIANCE", prices=prices, highs=highs, lows=lows)
    
    assert signal is not None
    assert signal["direction"] == "long"
    assert "sl_pct_override" in signal["features"]
    assert signal["features"]["bb_width_percentile"] <= 20.0
