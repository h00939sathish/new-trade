import json
import logging
from typing import Any, AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

OANDA_ENVIRONMENTS = {
    "practice": {"rest": "https://api-fxpractice.oanda.com/v3", "stream": "https://stream-fxpractice.oanda.com/v3"},
    "live": {"rest": "https://api-fxtrade.oanda.com/v3", "stream": "https://stream-fxtrade.oanda.com/v3"},
}


class OandaClient:
    def __init__(self, api_key: str, account_id: str, environment: str = "practice"):
        if environment not in OANDA_ENVIRONMENTS:
            raise ValueError(f"Invalid OANDA environment: {environment}. Must be 'practice' or 'live'.")
        if environment == "live":
            raise ValueError("Live OANDA environment is not supported in this implementation.")
        self.api_key = api_key
        self.account_id = account_id
        self.environment = environment
        urls = OANDA_ENVIRONMENTS[environment]
        self._rest_url = urls["rest"]
        self._stream_url = urls["stream"]
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self._rest_url}{path}"

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        with httpx.Client(timeout=30) as http:
            resp = http.get(self._url(path), headers=self._headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def _post(self, path: str, data: dict) -> dict[str, Any]:
        with httpx.Client(timeout=30) as http:
            resp = http.post(self._url(path), headers=self._headers, json=data)
            resp.raise_for_status()
            return resp.json()

    def _patch(self, path: str, data: dict) -> dict[str, Any]:
        with httpx.Client(timeout=30) as http:
            resp = http.patch(self._url(path), headers=self._headers, json=data)
            resp.raise_for_status()
            return resp.json()

    def _delete(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=30) as http:
            resp = http.delete(self._url(path), headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    # --- Account ---

    def get_account_summary(self) -> dict[str, Any]:
        return self._get(f"/accounts/{self.account_id}")

    # --- Instruments ---

    def get_instruments(self) -> list[dict[str, Any]]:
        data = self._get(f"/accounts/{self.account_id}/instruments")
        return data.get("instruments", [])

    # --- Candles ---

    def get_candles(
        self,
        instrument: str,
        granularity: str = "M1",
        count: int = 500,
        from_time: str | None = None,
        to_time: str | None = None,
        include_first: bool = False,
    ) -> list[dict[str, Any]]:
        params = {"granularity": granularity, "count": min(count, 5000), "includeFirst": str(include_first).lower()}
        if from_time:
            params["from"] = from_time
        if to_time:
            params["to"] = to_time
        data = self._get(f"/accounts/{self.account_id}/instruments/{instrument}/candles", params=params)
        return data.get("candles", [])

    def get_candle_bid_ask(
        self,
        instrument: str,
        granularity: str = "M1",
        count: int = 500,
        from_time: str | None = None,
        to_time: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            "granularity": granularity,
            "count": min(count, 5000),
            "price": "BA",
            "includeFirst": "false",
        }
        if from_time:
            params["from"] = from_time
        if to_time:
            params["to"] = to_time
        data = self._get(f"/accounts/{self.account_id}/instruments/{instrument}/candles", params=params)
        return data.get("candles", [])

    # --- Pricing ---

    async def stream_pricing(self, instruments: list[str]) -> AsyncGenerator[dict[str, Any], None]:
        params = {"instruments": ",".join(instruments)}
        url = f"{self._stream_url}/accounts/{self.account_id}/pricing/stream"
        async with httpx.AsyncClient(timeout=None) as http:
            async with http.stream("GET", url, headers=self._headers, params=params) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode pricing stream line: %s", line[:100])

    # --- Orders ---

    def place_order(
        self,
        instrument: str,
        units: int,
        side: str = "buy",
        order_type: str = "MARKET",
        client_order_id: str | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> dict[str, Any]:
        order_spec = {
            "type": order_type,
            "instrument": instrument,
            "units": abs(units) if side == "buy" else -abs(units),
        }
        if price is not None:
            order_spec["price"] = str(price)
        if trigger_price is not None and order_type in ("STOP", "STOP_LOSS"):
            order_spec["price"] = str(trigger_price)
        if client_order_id:
            order_spec["clientOrderID"] = client_order_id
        if stop_loss is not None:
            order_spec["stopLossOnFill"] = {"price": str(stop_loss)}
        if take_profit is not None:
            order_spec["takeProfitOnFill"] = {"price": str(take_profit)}
        data = {"order": order_spec}
        return self._post(f"/accounts/{self.account_id}/orders", data)

    def get_orders(self) -> list[dict[str, Any]]:
        data = self._get(f"/accounts/{self.account_id}/orders")
        return data.get("orders", [])

    def get_pending_orders(self) -> list[dict[str, Any]]:
        data = self._get(f"/accounts/{self.account_id}/orders", params={"state": "PENDING"})
        return data.get("orders", [])

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._delete(f"/accounts/{self.account_id}/orders/{order_id}")

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._get(f"/accounts/{self.account_id}/orders/{order_id}")

    # --- Positions ---

    def get_positions(self) -> list[dict[str, Any]]:
        data = self._get(f"/accounts/{self.account_id}/positions")
        return data.get("positions", [])

    def get_position(self, instrument: str) -> dict[str, Any]:
        return self._get(f"/accounts/{self.account_id}/positions/{instrument}")

    # --- Trades (open positions) ---

    def get_open_trades(self) -> list[dict[str, Any]]:
        data = self._get(f"/accounts/{self.account_id}/trades")
        return data.get("trades", [])

    # --- Transactions ---

    def get_transactions_since(self, since_id: str) -> list[dict[str, Any]]:
        data = self._get(f"/accounts/{self.account_id}/transactions/sinceid?id={since_id}")
        return data.get("transactions", [])

    def get_transaction(self, txn_id: str) -> dict[str, Any]:
        return self._get(f"/accounts/{self.account_id}/transactions/{txn_id}")
