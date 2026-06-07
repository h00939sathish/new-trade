import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from src.connectors.kite.client import KiteClient

logger = logging.getLogger("connector.kite.market_data")


class KiteMarketDataProvider:
    def __init__(self, client: KiteClient, on_tick: Any = None, on_ohlcv: Any = None):
        self._client = client
        self._on_tick = on_tick
        self._on_ohlcv = on_ohlcv
        self._instruments: list[dict[str, Any]] = []
        self._running = False
        self._task: asyncio.Task | None = None

    def set_tick_callback(self, callback: Any) -> None:
        self._on_tick = callback

    def set_ohlcv_callback(self, callback: Any) -> None:
        self._on_ohlcv = callback

    def add_instrument(
        self,
        tradingsymbol: str,
        exchange: str = "NSE",
        instrument_token: int | None = None,
    ) -> None:
        self._instruments.append(
            {
                "tradingsymbol": tradingsymbol,
                "exchange": exchange,
                "instrument_token": instrument_token,
            }
        )
        logger.info("Added instrument: %s (%s)", tradingsymbol, exchange)

    def remove_instrument(self, tradingsymbol: str) -> None:
        self._instruments = [i for i in self._instruments if i["tradingsymbol"] != tradingsymbol]

    async def start(self, poll_interval: float = 1.0) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(poll_interval))
        logger.info("Market data polling started (interval=%.1fs)", poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Market data polling stopped")

    async def get_historical(
        self,
        instrument_token: int,
        interval: str = "day",
        days: int = 30,
    ) -> list[dict[str, Any]]:
        from datetime import timedelta

        to_date = datetime.now(UTC)
        from_date = to_date - timedelta(days=days)
        return self._client.get_historical_data(
            instrument_token=instrument_token,
            interval=interval,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
        )

    async def search(self, query: str) -> list[dict[str, Any]]:
        return self._client.search_instruments(query)

    async def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        return self._client.get_ltp(instruments)

    async def _poll_loop(self, interval: float) -> None:
        while self._running:
            try:
                if not self._instruments:
                    await asyncio.sleep(interval)
                    continue
                symbols = [f"{i['exchange']}:{i['tradingsymbol']}" for i in self._instruments]
                quote_data = self._client.get_quote(symbols)
                for symbol, data in quote_data.items():
                    if self._on_tick:
                        # Extract top level bid and ask
                        buy_levels = data.get("buy") or data.get("depth", {}).get("buy", [])
                        sell_levels = data.get("sell") or data.get("depth", {}).get("sell", [])
                        bid = buy_levels[0].get("price") if buy_levels else None
                        ask = sell_levels[0].get("price") if sell_levels else None

                        await self._on_tick(
                            {
                                "instrument": symbol.split(":")[1] if ":" in symbol else symbol,
                                "exchange": symbol.split(":")[0] if ":" in symbol else "NSE",
                                "last_price": data.get("last_price", 0),
                                "volume": data.get("volume"),
                                "depth": data.get("depth"),
                                "bid": bid,
                                "ask": ask,
                            }
                        )
            except Exception as e:
                logger.error("Poll error: %s", e)
            await asyncio.sleep(interval)
