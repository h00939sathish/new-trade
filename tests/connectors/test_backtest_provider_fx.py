import pytest


class TestBacktestProviderFX:
    @pytest.mark.asyncio
    async def test_fetch_fx_candles_no_suffix(self):
        from src.connectors.backtest_provider import fetch_historical_1m_candles

        candles = await fetch_historical_1m_candles("EURUSD=X", exchange="FX", days=1)
        assert len(candles) > 0
        assert "open" in candles[0]
        assert "high" in candles[0]
        assert "low" in candles[0]
        assert "close" in candles[0]
