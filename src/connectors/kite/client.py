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
        self._placeholder_mode = False
        self.connection_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_placeholder_mode(self) -> bool:
        return self._placeholder_mode

    async def connect(self) -> None:
        if not self.api_key or not self.access_token:
            if settings.live_trading_enabled:
                raise ConnectionError("Kite credentials are required when live trading is enabled")
            logger.warning("Kite credentials not configured; using placeholder mode")
            self._connected = True
            self._placeholder_mode = True
            return
        try:
            import kiteconnect

            self._kite = kiteconnect.KiteConnect(api_key=self.api_key)
            self._kite.set_access_token(self.access_token)
            from src.utils.retry import with_retry

            profile = await with_retry(
                lambda: self._kite.profile(), max_retries=3, exceptions=(Exception,)
            )
            self._connected = True
            self._placeholder_mode = False
            logger.info("Connected to Kite: %s", profile.get("user_id", "unknown"))
        except ImportError:
            if settings.live_trading_enabled:
                raise
            logger.warning("kiteconnect not installed; using placeholder mode")
            self._connected = True
            self._placeholder_mode = True
        except Exception as e:
            self._connected = False
            self._placeholder_mode = False
            self.connection_error = str(e)
            logger.warning("Kite connection failed (will use paper mode): %s", e)

    async def disconnect(self) -> None:
        self._kite = None
        self._connected = False
        self._placeholder_mode = False
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
            try:
                return self._kite.quote(instruments)  # type: ignore
            except Exception as e:
                logger.error("Kite quote fetch failed: %s. Using mock quote.", e)

        # Generate mock quote with realistic depth for paper/placeholder mode
        quotes = {}
        for inst in instruments:
            symbol = inst.split(":")[1] if ":" in inst else inst
            price = 100.0 if symbol == "TEST" else 2500.0  # mock price base
            mock_depth = {
                "buy": [
                    {"price": round(price - i * 0.05, 2), "quantity": 100 * (i + 1), "orders": 3}
                    for i in range(5)
                ],
                "sell": [
                    {
                        "price": round(price + (i + 1) * 0.05, 2),
                        "quantity": 80 * (i + 1),
                        "orders": 2,
                    }
                    for i in range(5)
                ],
            }
            quotes[inst] = {
                "last_price": price,
                "volume": 500000,
                "depth": mock_depth,
                "buy": mock_depth["buy"],
                "sell": mock_depth["sell"],
            }
        return quotes
