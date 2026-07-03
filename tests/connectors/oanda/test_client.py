import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOandaClient:
    def test_init_rejects_live_env(self):
        from src.connectors.oanda.client import OandaClient

        with pytest.raises(ValueError, match="(?i)live"):
            OandaClient(api_key="test", account_id="test", environment="live")

    def test_init_accepts_practice(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test", account_id="test", environment="practice")
        assert client.environment == "practice"

    def test_raises_on_invalid_environment(self):
        from src.connectors.oanda.client import OandaClient

        with pytest.raises(ValueError, match="Invalid OANDA environment"):
            OandaClient(api_key="test", account_id="test", environment="invalid")

    def test_get_instruments_parses_response(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "instruments": [
                {
                    "name": "XAU_USD",
                    "type": "CFD",
                    "displayName": "Gold",
                    "pipLocation": -1,
                    "tradeUnitsPrecision": 0,
                    "minimumTradeSize": "1",
                }
            ]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.Client") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.__enter__.return_value = mock_inst
            mock_inst.get.return_value = mock_resp
            mock_cls.return_value = mock_inst

            instruments = client.get_instruments()

        assert len(instruments) == 1
        assert instruments[0]["name"] == "XAU_USD"

    def test_get_instruments_empty_response(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.Client") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.__enter__.return_value = mock_inst
            mock_inst.get.return_value = mock_resp
            mock_cls.return_value = mock_inst

            instruments = client.get_instruments()

        assert instruments == []

    def test_api_error_propagates(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        with patch("httpx.Client") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.__enter__.return_value = mock_inst
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = Exception("API error")
            mock_inst.get.return_value = mock_resp
            mock_cls.return_value = mock_inst

            with pytest.raises(Exception):
                client.get_account_summary()

    def test_get_candles_empty_response(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.Client") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.__enter__.return_value = mock_inst
            mock_inst.get.return_value = mock_resp
            mock_cls.return_value = mock_inst

            candles = client.get_candles("XAU_USD")

        assert candles == []

    def test_place_order(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"orderCreateTransaction": {"id": "12345"}, "lastTransactionID": "12345"}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.Client") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.__enter__.return_value = mock_inst
            mock_inst.post.return_value = mock_resp
            mock_cls.return_value = mock_inst

            result = client.place_order(instrument="XAU_USD", units=10, side="buy")

        assert result["orderCreateTransaction"]["id"] == "12345"

    def test_cancel_order(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"orderCancelTransaction": {"id": "67890"}}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.Client") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.__enter__.return_value = mock_inst
            mock_inst.delete.return_value = mock_resp
            mock_cls.return_value = mock_inst

            result = client.cancel_order("order-1")

        assert result["orderCancelTransaction"]["id"] == "67890"

    @pytest.mark.asyncio
    async def test_stream_pricing(self):
        from src.connectors.oanda.client import OandaClient

        client = OandaClient(api_key="test_key", account_id="test_id", environment="practice")

        price_line = '{"type":"PRICE","instrument":"XAU_USD","time":"2026-07-03T00:00:00Z","bids":[{"price":"2350.0"}],"asks":[{"price":"2350.5"}]}'
        heartbeat_line = '{"type":"HEARTBEAT","time":"2026-07-03T00:00:01Z"}'

        mock_stream = MagicMock()
        mock_stream.aiter_lines.return_value = AsyncMock(side_effect=[[price_line, heartbeat_line]])

        # We need aiter_lines to be async iterable
        async def aiter_lines():
            yield price_line
            yield heartbeat_line

        mock_stream.aiter_lines = aiter_lines
        mock_stream.raise_for_status.return_value = None

        mock_async_client = MagicMock()
        mock_async_client.__aenter__.return_value = mock_async_client
        mock_async_client.stream.return_value.__aenter__.return_value = mock_stream

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = mock_async_client

            results = []
            async for tick in client.stream_pricing(["XAU_USD"]):
                results.append(tick)

        assert len(results) == 2
        assert results[0]["type"] == "PRICE"
        assert results[1]["type"] == "HEARTBEAT"
