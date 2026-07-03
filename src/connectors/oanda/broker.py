import asyncio
import logging
from typing import Any

from src.connectors.oanda.client import OandaClient
from src.schemas.events import Exchange, OrderSide, OrderType, ProductType

logger = logging.getLogger(__name__)


class OandaBroker:
    def __init__(self, client: OandaClient):
        self._client = client

    async def place_order(
        self,
        tradingsymbol: str,
        exchange: Exchange,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        product: ProductType,
        price: float | None = None,
        trigger_price: float | None = None,
        variety: str = "market",
        tag: str | None = None,
    ) -> str:
        oanda_side = "buy" if side == OrderSide.BUY else "sell"
        oanda_type = "MARKET" if order_type == OrderType.MARKET else "LIMIT" if order_type == OrderType.LIMIT else "STOP"
        result = await asyncio.to_thread(
            self._client.place_order,
            instrument=tradingsymbol,
            units=quantity,
            side=oanda_side,
            order_type=oanda_type,
            client_order_id=tag,
            price=price,
            trigger_price=trigger_price,
        )
        txn = result.get("orderCreateTransaction", result)
        order_id = txn.get("id") or txn.get("orderID", "")
        logger.info("OANDA order placed: %s %s %d (orderID=%s)", oanda_side, tradingsymbol, quantity, order_id)
        return order_id

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        logger.info("Cancelling OANDA order: %s", order_id)
        return await asyncio.to_thread(self._client.cancel_order, order_id)

    async def get_orders(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._client.get_orders)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._client.get_order, order_id)

    async def get_positions(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._client.get_positions)

    async def get_open_trades(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._client.get_open_trades)
