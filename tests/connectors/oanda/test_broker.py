from unittest.mock import MagicMock

import pytest

from src.connectors.oanda.client import OandaClient
from src.schemas.events import Exchange, OrderSide, OrderType, ProductType


class TestOandaBroker:
    @pytest.mark.asyncio
    async def test_place_order_returns_order_id(self):
        from src.connectors.oanda.broker import OandaBroker
        from src.connectors.oanda.client import OandaClient

        client = MagicMock(spec=OandaClient)
        client.place_order.return_value = {
            "orderCreateTransaction": {"id": "12345"},
            "lastTransactionID": "12345",
        }
        broker = OandaBroker(client)
        order_id = await broker.place_order(
            tradingsymbol="XAU_USD",
            exchange=Exchange.FX,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            product=ProductType.NRML,
            price=None,
        )
        assert order_id == "12345"

    @pytest.mark.asyncio
    async def test_place_limit_order_passes_price(self):
        from src.connectors.oanda.broker import OandaBroker

        client = MagicMock(spec=OandaClient)
        client.place_order.return_value = {"orderCreateTransaction": {"id": "LIMIT123"}}
        broker = OandaBroker(client)
        order_id = await broker.place_order(
            tradingsymbol="XAU_USD", exchange=Exchange.FX, side=OrderSide.BUY,
            order_type=OrderType.LIMIT, quantity=10, product=ProductType.NRML,
            price=2350.0,
        )
        assert order_id == "LIMIT123"
        client.place_order.assert_called_once()
        _, kwargs = client.place_order.call_args
        assert kwargs.get("price") == 2350.0

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        from src.connectors.oanda.broker import OandaBroker

        client = MagicMock()
        broker = OandaBroker(client)
        await broker.cancel_order("order-1")
        client.cancel_order.assert_called_once_with("order-1")

    @pytest.mark.asyncio
    async def test_get_orders(self):
        from src.connectors.oanda.broker import OandaBroker

        client = MagicMock()
        client.get_orders.return_value = [{"id": "1", "instrument": "XAU_USD"}]
        broker = OandaBroker(client)
        orders = await broker.get_orders()
        assert len(orders) == 1
        assert orders[0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_get_order(self):
        from src.connectors.oanda.broker import OandaBroker

        client = MagicMock()
        client.get_order.return_value = {"id": "1", "instrument": "XAU_USD"}
        broker = OandaBroker(client)
        order = await broker.get_order("1")
        assert order["id"] == "1"
        client.get_order.assert_called_once_with("1")

    @pytest.mark.asyncio
    async def test_get_positions(self):
        from src.connectors.oanda.broker import OandaBroker

        client = MagicMock()
        client.get_positions.return_value = [{"instrument": "XAU_USD", "units": "10"}]
        broker = OandaBroker(client)
        positions = await broker.get_positions()
        assert len(positions) == 1
        assert positions[0]["instrument"] == "XAU_USD"

    @pytest.mark.asyncio
    async def test_get_open_trades(self):
        from src.connectors.oanda.broker import OandaBroker

        client = MagicMock()
        client.get_open_trades.return_value = [{"id": "1", "instrument": "XAU_USD"}]
        broker = OandaBroker(client)
        trades = await broker.get_open_trades()
        assert len(trades) == 1
        assert trades[0]["id"] == "1"
