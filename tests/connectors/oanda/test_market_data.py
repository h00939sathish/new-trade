import pytest
from unittest.mock import AsyncMock, MagicMock


class TestOandaMarketDataProvider:
    @pytest.mark.asyncio
    async def test_add_instrument_and_start(self):
        from src.connectors.oanda.market_data import OandaMarketDataProvider

        provider = OandaMarketDataProvider()
        provider.add_instrument("XAU_USD", "FX")
        assert "XAU_USD" in provider._instruments

    @pytest.mark.asyncio
    async def test_callbacks_are_set(self):
        from src.connectors.oanda.market_data import OandaMarketDataProvider

        provider = OandaMarketDataProvider()
        tick_cb = MagicMock()
        ohlcv_cb = MagicMock()
        provider.set_tick_callback(tick_cb)
        provider.set_ohlcv_callback(ohlcv_cb)
        assert provider._on_tick is tick_cb
        assert provider._on_ohlcv is ohlcv_cb

    @pytest.mark.asyncio
    async def test_get_historical_returns_candles(self):
        from src.connectors.oanda.market_data import OandaMarketDataProvider
        from src.connectors.oanda.client import OandaClient

        client = MagicMock(spec=OandaClient)
        client.get_candles.return_value = [
            {"time": "2026-07-01T00:00:00.000000000Z", "mid": {"o": "2350.0", "h": "2351.0", "l": "2349.0", "c": "2350.5", "v": 100}}
        ]
        provider = OandaMarketDataProvider(client=client)
        candles = await provider.get_historical("XAU_USD", interval_minutes=1, days=1)
        assert len(candles) == 1
        assert candles[0]["open"] == 2350.0
        assert candles[0]["instrument"] == "XAU_USD"
