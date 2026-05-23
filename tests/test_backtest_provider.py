import pytest

from src.connectors.backtest_provider import (
    BacktestDataProvider,
    generate_synthetic_ticks,
)


def test_synthetic_ticks_structure():
    ticks = generate_synthetic_ticks(100)
    assert len(ticks) == 100
    for t in ticks:
        assert "instrument" in t
        assert "exchange" in t
        assert "price" in t
        assert "volume" in t
        assert t["instrument"] == "TEST"
        assert t["exchange"] == "NSE"


def test_synthetic_ticks_default_count():
    ticks = generate_synthetic_ticks()
    assert len(ticks) == 5000


def test_synthetic_ticks_price_range():
    ticks = generate_synthetic_ticks(500)
    prices = [t["price"] for t in ticks]
    assert all(p >= 10.0 for p in prices)
    assert max(prices) > 90
    assert min(prices) < 110


class FakeProvider:
    def __init__(self, candles=None):
        self._candles = candles or []

    async def get_historical(self, tradingsymbol, interval_minutes, days, exchange):
        return self._candles


@pytest.mark.asyncio
async def test_backtest_provider_no_instruments():
    provider = BacktestDataProvider(market_data_provider=FakeProvider())
    ticks = await provider.get_backtest_ticks(days=10)
    assert len(ticks) == 5000
    assert ticks[0]["instrument"] == "TEST"


@pytest.mark.asyncio
async def test_backtest_provider_with_candles():
    candles = [
        {"open": 100, "high": 105, "low": 99, "close": 103, "volume": 50000, "timestamp": "2026-05-20T00:00:00"},
        {"open": 103, "high": 108, "low": 102, "close": 107, "volume": 60000, "timestamp": "2026-05-21T00:00:00"},
    ]
    provider = BacktestDataProvider(
        market_data_provider=FakeProvider(candles),
        instruments=["RELIANCE"],
    )
    ticks = await provider.get_backtest_ticks(days=10)
    assert len(ticks) > 0
    for t in ticks:
        assert t["instrument"] == "RELIANCE"
        assert t["exchange"] == "NSE"
        assert t["price"] > 0
        assert t["volume"] > 0


@pytest.mark.asyncio
async def test_backtest_provider_add_instrument():
    provider = BacktestDataProvider(market_data_provider=FakeProvider())
    provider.add_instrument("TCS")
    assert "TCS" in provider._instruments
    provider.add_instrument("TCS")
    assert len(provider._instruments) == 1


@pytest.mark.asyncio
async def test_backtest_provider_historical_proxy():
    candles = [{"open": 100, "high": 105, "low": 99, "close": 103}]
    provider = BacktestDataProvider(
        market_data_provider=FakeProvider(candles),
    )
    result = await provider.get_historical("TEST")
    assert result == candles
