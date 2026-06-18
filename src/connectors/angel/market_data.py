import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from src.connectors.angel.client import AngelClient, AngelClientError
from src.connectors.angel.websocket import (
    AngelWebSocketClient,
    AngelWebSocketMode,
    AngelWebSocketSubscription,
)
from src.connectors.yahoo import get_ltp_yahoo as _yahoo_ltp

logger = logging.getLogger("connector.angel.market_data")


class AngelMarketDataProvider:
    def __init__(
        self,
        client: AngelClient | None = None,
        on_tick: Callable | None = None,
        on_ohlcv: Callable | None = None,
        prefer_websocket: bool = True,
        websocket_factory: Callable[..., AngelWebSocketClient] | None = None,
    ):
        self._client = client or AngelClient()
        self._on_tick = on_tick
        self._on_ohlcv = on_ohlcv
        self._prefer_websocket = prefer_websocket
        self._websocket_factory = websocket_factory or AngelWebSocketClient
        self._websocket: AngelWebSocketClient | None = None
        self._instruments: list[dict[str, Any]] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._poll_interval = 1.0

    def set_tick_callback(self, callback: Callable) -> None:
        self._on_tick = callback

    def set_ohlcv_callback(self, callback: Callable) -> None:
        self._on_ohlcv = callback

    def add_instrument(
        self,
        tradingsymbol: str,
        exchange: str = "NSE",
        symbol_token: str | None = None,
    ) -> None:
        self._instruments.append(
            {
                "tradingsymbol": tradingsymbol,
                "exchange": exchange,
                "symbol_token": symbol_token,
            }
        )
        logger.info("Angel added instrument: %s (%s)", tradingsymbol, exchange)

    def remove_instrument(self, tradingsymbol: str) -> None:
        self._instruments = [i for i in self._instruments if i["tradingsymbol"] != tradingsymbol]

    async def start(self, poll_interval: float = 1.0) -> None:
        if self._running:
            return
        self._running = True
        self._poll_interval = poll_interval
        await self._client.connect()
        if self._prefer_websocket and await self._start_websocket():
            logger.info("Angel market data WebSocket started")
            return
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Angel market data polling started (interval=%.1fs)", poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._websocket:
            await self._websocket.close()
            self._websocket = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._client.disconnect()
        logger.info("Angel market data stopped")

    async def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        try:
            return await self._client.get_ltp(instruments)
        except Exception:
            pass
        try:
            return await _yahoo_ltp(instruments)
        except Exception:
            return {}

    async def get_historical(
        self,
        tradingsymbol: str,
        interval_minutes: int = 1,
        days: int = 7,
        exchange: str = "NSE",
    ) -> list[dict[str, Any]]:
        interval_map = {
            1: "minute",
            3: "3minute",
            5: "5minute",
            15: "15minute",
            60: "hour",
            1440: "day",
        }
        interval = interval_map.get(interval_minutes, "minute")
        now = datetime.now(UTC)
        from_date = now - timedelta(days=days)
        try:
            return await self._client.get_historical_data(
                instrument=tradingsymbol,
                interval=interval,
                from_date=from_date.strftime("%Y-%m-%d %H:%M"),
                to_date=now.strftime("%Y-%m-%d %H:%M"),
                exchange=exchange,
            )
        except AngelClientError as e:
            logger.error("Angel historical fetch failed for %s: %s", tradingsymbol, e)
            return []

    async def _poll_loop(self) -> None:
        last_ohlcv_fetch: dict[str, float] = {}
        ohlcv_interval = 60.0
        angel_degraded = False
        angel_retry_counter = 0

        while self._running:
            try:
                if not self._instruments:
                    await asyncio.sleep(self._poll_interval)
                    continue

                angel_retry_counter += 1
                retry_angel = angel_degraded and angel_retry_counter >= 60

                for inst in self._instruments:
                    ltp_data: dict[str, Any] = {}
                    try:
                        if not angel_degraded or retry_angel:
                            try:
                                symbols = [f"{inst['exchange']}:{inst['tradingsymbol']}"]
                                ltp_data = await self._client.get_ltp(symbols)
                                if ltp_data:
                                    angel_degraded = False
                                    angel_retry_counter = 0
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug("LTP poll failed for %s: %s", inst["tradingsymbol"], e)

                    if not ltp_data:
                        try:
                            ltp_data = await _yahoo_ltp(
                                [
                                    f"{inst['exchange']}:{inst['tradingsymbol']}",
                                ]
                            )
                        except Exception:
                            pass

                    for value in ltp_data.values():
                        if self._on_tick:
                            await _invoke_callback(
                                self._on_tick,
                                {
                                    "instrument": inst["tradingsymbol"],
                                    "exchange": inst["exchange"],
                                    "last_price": value.get("last_price", 0),
                                    "volume": value.get("volume"),
                                },
                            )

                now = datetime.now(UTC).timestamp()
                for inst in self._instruments:
                    sym = inst["tradingsymbol"]
                    needs_fetch = (
                        sym not in last_ohlcv_fetch
                        or (now - last_ohlcv_fetch[sym]) >= ohlcv_interval
                    )
                    if needs_fetch:
                        last_ohlcv_fetch[sym] = now
                        if self._on_ohlcv:
                            try:
                                to_ts = datetime.now(UTC)
                                from_ts = to_ts - timedelta(minutes=5)
                                candles = await self._client.get_historical_data(
                                    instrument=sym,
                                    interval="minute",
                                    from_date=from_ts.strftime("%Y-%m-%d %H:%M"),
                                    to_date=to_ts.strftime("%Y-%m-%d %H:%M"),
                                    exchange=inst["exchange"],
                                )
                                if candles:
                                    c = candles[-1]
                                    await _invoke_callback(
                                        self._on_ohlcv,
                                        {
                                            "instrument": sym,
                                            "exchange": inst["exchange"],
                                            "interval": "minute",
                                            "open": c["open"],
                                            "high": c["high"],
                                            "low": c["low"],
                                            "close": c["close"],
                                            "volume": c["volume"],
                                        },
                                    )
                            except AngelClientError as e:
                                logger.debug("OHLCV fetch skipped for %s: %s", sym, e)

            except AngelClientError as e:
                logger.error("Angel poll error: %s", e)
            except Exception as e:
                logger.error("Angel poll error: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def _start_websocket(self) -> bool:
        if not self._instruments:
            return False
        try:
            await self._client.ensure_token()
            if not all(
                [
                    self._client.api_key,
                    self._client.client_id,
                    self._client.jwt_token,
                    self._client.feed_token,
                ]
            ):
                return False

            subscriptions = []
            for inst in self._instruments:
                symbol = inst["tradingsymbol"]
                exchange = inst["exchange"]
                token = inst.get("symbol_token")
                if not token:
                    token = await self._client.resolve_token(symbol, exchange)
                if token:
                    subscriptions.append(AngelWebSocketSubscription(exchange, token, symbol))
            if not subscriptions:
                return False

            self._websocket = self._websocket_factory(
                api_key=self._client.api_key,
                client_code=self._client.client_id,
                auth_token=self._client.jwt_token,
                feed_token=self._client.feed_token,
                on_tick=self._handle_websocket_tick,
                on_disconnect=self._handle_websocket_disconnect,
            )
            await self._websocket.connect()
            await self._websocket.subscribe(subscriptions, mode=AngelWebSocketMode.LTP)
            return True
        except Exception as e:
            self._websocket = None
            logger.warning("Angel WebSocket unavailable; falling back to polling: %s", e)
            return False

    async def _handle_websocket_tick(self, tick: dict[str, Any]) -> None:
        if self._on_tick:
            await _invoke_callback(self._on_tick, tick)

    async def _handle_websocket_disconnect(self, reason: str) -> None:
        if not self._running:
            return
        logger.warning(
            "Angel WebSocket disconnected; attempting auto-reconnect: %s",
            reason,
        )


async def _invoke_callback(callback: Callable, payload: dict[str, Any]) -> None:
    result = callback(payload)
    if inspect.isawaitable(result):
        await result
