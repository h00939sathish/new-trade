import logging
from typing import Any

from src.connectors.kite.client import KiteClient
from src.schemas.events import Exchange, OrderSide, OrderType, ProductType

logger = logging.getLogger("connector.kite.broker")


class KiteBroker:
    def __init__(self, client: KiteClient):
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
        variety: str = "regular",
        tag: str | None = None,
    ) -> str:
        order_params: dict[str, Any] = {
            "tradingsymbol": tradingsymbol,
            "exchange": exchange.value,
            "transaction_type": side.value.upper(),
            "order_type": order_type.value.upper(),
            "quantity": quantity,
            "product": product.value,
            "variety": variety,
        }
        if price is not None:
            order_params["price"] = price
        if trigger_price is not None:
            order_params["trigger_price"] = trigger_price
        if tag is not None:
            order_params["tag"] = tag

        order_id = self._client.place_order(**order_params)
        logger.info(
            "Order placed: %s %s %d %s @ %.2f (id=%s)",
            side.value.upper(), tradingsymbol, quantity,
            order_type.value.upper(), price or 0, order_id,
        )
        return order_id

    async def modify_order(
        self,
        order_id: str,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        order_type: OrderType | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"order_id": order_id}
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if order_type is not None:
            params["order_type"] = order_type.value.upper()
        result = self._client.modify_order(**params)
        logger.info("Order modified: %s", order_id)
        return result

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        result = self._client.cancel_order(order_id)
        logger.info("Order cancelled: %s", order_id)
        return result

    async def get_orders(self) -> list[dict[str, Any]]:
        return self._client.get_orders()

    async def get_positions(self) -> list[dict[str, Any]]:
        return self._client.get_positions()

    async def get_holdings(self) -> list[dict[str, Any]]:
        return self._client.get_holdings()

    async def get_order_history(self, order_id: str) -> list[dict[str, Any]]:
        return self._client.get_order_history(order_id)

    async def get_trades(self) -> list[dict[str, Any]]:
        return self._client.get_trades()

    async def get_margins(self) -> dict[str, Any]:
        return self._client.get_margins()
