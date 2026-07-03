import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "oanda"


@pytest.fixture
def instruments_fixture():
    return json.loads((FIXTURE_DIR / "instruments.json").read_text())


@pytest.fixture
def candles_fixture():
    return json.loads((FIXTURE_DIR / "candles_xau_usd.json").read_text())


class TestOandaIntegration:
    def test_instrument_discovery_flow(self, instruments_fixture):
        from src.connectors.oanda.client import OandaClient
        from src.connectors.oanda.market_data import OandaMarketDataProvider
        client = MagicMock(spec=OandaClient)
        client.get_instruments.return_value = instruments_fixture["instruments"]
        provider = OandaMarketDataProvider(client=client)
        provider.add_instrument("XAU_USD", "FX")
        provider.add_instrument("EUR_USD", "FX")
        instruments = client.get_instruments()
        names = [i["name"] for i in instruments]
        assert "XAU_USD" in names
        assert "EUR_USD" in names

    def test_candle_parsing_roundtrip(self, candles_fixture):
        from src.connectors.oanda.market_data import OandaMarketDataProvider
        provider = OandaMarketDataProvider()
        parsed = provider._parse_candle("XAU_USD", candles_fixture["candles"][0])
        assert parsed is not None
        assert parsed["instrument"] == "XAU_USD"
        assert isinstance(parsed["open"], float)
        assert parsed["open"] > 0

    def test_broker_place_order_uses_client(self):
        from src.connectors.oanda.broker import OandaBroker
        from src.connectors.oanda.client import OandaClient
        from src.schemas.events import Exchange, OrderSide, OrderType, ProductType
        client = MagicMock(spec=OandaClient)
        client.place_order.return_value = {"orderCreateTransaction": {"id": "TEST123"}}
        broker = OandaBroker(client)
        import asyncio
        order_id = asyncio.run(broker.place_order(
            tradingsymbol="XAU_USD", exchange=Exchange.FX,
            side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=1, product=ProductType.NRML,
        ))
        assert order_id == "TEST123"
