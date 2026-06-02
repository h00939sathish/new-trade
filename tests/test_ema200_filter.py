import pytest
from src.core.regime.ema200_filter import EMA200Filter, RegimeState

def test_no_trade_insufficient_data():
    filter_ = EMA200Filter(period=10, slope_lookback=2)
    closes = [100.0] * 5
    assert filter_.evaluate(closes) == RegimeState.NO_TRADE

def test_trend_long_allowed():
    filter_ = EMA200Filter(period=10, slope_lookback=2)
    # create an uptrend
    closes = list(range(100, 120))  # 20 elements
    # SMA of first 10 = 104.5. 
    # Since prices are rising, EMA will be below price and rising
    assert filter_.evaluate(closes) == RegimeState.TREND_LONG_ALLOWED

def test_trend_short_allowed():
    filter_ = EMA200Filter(period=10, slope_lookback=2)
    # create a downtrend
    closes = list(range(120, 100, -1))
    assert filter_.evaluate(closes) == RegimeState.TREND_SHORT_ALLOWED

def test_mean_reversion_only():
    filter_ = EMA200Filter(period=10, slope_lookback=2)
    closes = [100.0] * 15
    # Flat line: slope is 0, price == EMA
    assert filter_.evaluate(closes) == RegimeState.MEAN_REVERSION_ONLY
