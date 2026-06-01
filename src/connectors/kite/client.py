import logging
from typing import Any

from src.config.settings import settings

logger = logging.getLogger("connector.kite")


class KiteClient:
    def __init__(self, api_key: str | None = None, access_token: str | None = None):
        self.api_key = api_key or settings.kite_api_key
        self.access_token = access_token or settings.kite_access_token
        self._kite: Any = None
        self._connected = False
        self.connection_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        if not self.api_key or not self.access_token:
            logger.warning("Kite credentials not configured; using placeholder mode")
            self._connected = True
            return
        try:
            import kiteconnect
            self._kite = kiteconnect.KiteConnect(api_key=self.api_key)
            self._kite.set_access_token(self.access_token)
            from src.utils.retry import with_retry
            profile = await with_retry(
                lambda: self._kite.profile(),
                max_retries=3,
                exceptions=(Exception,)
            )
            self._connected = True
            logger.info("Connected to Kite: %s", profile.get("user_id", "unknown"))
        except ImportError:
            logger.warning("kiteconnect not installed; using placeholder mode")
            self._connected = True
        except Exception as e:
            self._connected = False
            self.connection_error = str(e)
            logger.warning("Kite connection failed (will use paper mode): %s", e)

    async def disconnect(self) -> None:
        self._kite = None
        self._connected = False
        logger.info("Kite client disconnected")

    def get_profile(self) -> dict[str, Any]:
        if self._kite and self._connected:
            return self._kite.profile()  # type: ignore
        return {"user_id": "placeholder", "user_name": "Paper Trading"}

    def get_margins(self) -> dict[str, Any]:
        if self._kite and self._connected:
            return self._kite.margins()  # type: ignore
        return {"equity": {"available": {"cash": 1000000}}}

    def get_positions(self) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            result = self._kite.positions()  # type: ignore
            return result.get("day", [])
        return []

    def get_holdings(self) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            return self._kite.holdings()  # type: ignore
        return []

    def place_order(self, **kwargs: Any) -> str:
        if self._kite and self._connected:
            variety = kwargs.pop("variety", "regular")
            result = self._kite.place_order(variety=variety, **kwargs)  # type: ignore
            return result.get("order_id", "")
        order_id = f"paper_{kwargs.get('tradingsymbol', 'unknown')}_{hash(str(kwargs)) % 10000}"
        logger.info("Paper order placed: %s", order_id)
        return order_id

    def modify_order(self, order_id: str, **kwargs: Any) -> dict[str, Any]:
        if self._kite and self._connected:
            return self._kite.modify_order(order_id=order_id, **kwargs)  # type: ignore
        return {"order_id": order_id}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        if self._kite and self._connected:
            return self._kite.cancel_order(order_id=order_id)  # type: ignore
        return {"order_id": order_id}

    def get_orders(self) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            return self._kite.orders()  # type: ignore
        return []

    def get_order_history(self, order_id: str) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            return self._kite.order_history(order_id=order_id)  # type: ignore
        return []

    def get_trades(self) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            return self._kite.trades()  # type: ignore
        return []

    def search_instruments(self, query: str) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            return self._kite.search_instruments(query=query)  # type: ignore
        return [
            {"tradingsymbol": "RELIANCE", "exchange": "NSE", "instrument_token": 12345},
            {"tradingsymbol": "TCS", "exchange": "NSE", "instrument_token": 12346},
        ]

    def get_historical_data(
        self,
        instrument_token: int,
        interval: str = "day",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._kite and self._connected:
            return self._kite.historical_data(  # type: ignore
                instrument_token=instrument_token,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
        return []

    def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        if self._kite and self._connected:
            return self._kite.ltp(instruments)  # type: ignore
        return {i: {"last_price": 100.0} for i in instruments}

    def get_quote(self, instruments: list[str]) -> dict[str, Any]:
        if self._kite and self._connected:
            return self._kite.quote(instruments)  # type: ignore
        return {}
