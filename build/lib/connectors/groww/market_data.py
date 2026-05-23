import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from src.connectors.groww.client import GrowwAPIError, GrowwClient

logger = logging.getLogger("connector.groww.market_data")


class GrowwMarketDataProvider:
    def __init__(self, client: GrowwClient | None = None, on_tick: Callable | None = None, on_ohlcv: Callable | None = None):
        self._client = client or GrowwClient()
        self._on_tick = on_tick
        self._on_ohlcv = on_ohlcv
        self._instruments: list[dict[str, Any]] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._poll_interval = 1.0

    def set_tick_callback(self, callback: Callable) -> None:
        self._on_tick = callback

    def set_ohlcv_callback(self, callback: Callable) -> None:
        self._on_ohlcv = callback

    def add_instrument(self, tradingsymbol: str, exchange: str = "NSE") -> None:
        self._instruments.append({"tradingsymbol": tradingsymbol, "exchange": exchange})
        logger.info("Added instrument: %s (%s)", tradingsymbol, exchange)

    def remove_instrument(self, tradingsymbol: str) -> None:
        self._instruments = [i for i in self._instruments if i["tradingsymbol"] != tradingsymbol]

    async def start(self, poll_interval: float = 1.0) -> None:
        if self._running:
            return
        self._running = True
        self._poll_interval = poll_interval
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Groww market data polling started (interval=%.1fs)", poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._client.close()
        logger.info("Groww market data polling stopped")

    async def _poll_loop(self) -> None:
        last_ohlcv_fetch: dict[str, float] = {}
        ohlcv_interval = 60.0

        while self._running:
            try:
                if not self._instruments:
                    await asyncio.sleep(self._poll_interval)
                    continue

                symbols = [i["tradingsymbol"] for i in self._instruments]
                ltp_data = await self._client.get_ltp(symbols)

                if "payload" in ltp_data:
                    for key, value in ltp_data["payload"].items():
                        if self._on_tick:
                            parts = key.split("_", 1)
                            exchange = parts[0] if len(parts) > 1 else "NSE"
                            instr = parts[1] if len(parts) > 1 else key
                            await self._on_tick({
                                "instrument": instr,
                                "exchange": exchange,
                                "last_price": float(value) if not isinstance(value, dict) else value.get("last_price", 0),
                                "volume": None,
                            })

                now = datetime.now(UTC).timestamp()
                for inst in self._instruments:
                    sym = inst["tradingsymbol"]
                    if sym not in last_ohlcv_fetch or (now - last_ohlcv_fetch[sym]) >= ohlcv_interval:
                        last_ohlcv_fetch[sym] = now
                        if self._on_ohlcv:
                            try:
                                ohlc_data = await self._client.get_ohlc([sym])
                                if "payload" in ohlc_data:
                                    for key, value in ohlc_data["payload"].items():
                                        parts = key.split("_", 1)
                                        instr = parts[1] if len(parts) > 1 else key
                                        exchange = parts[0] if len(parts) > 1 else "NSE"
                                        if isinstance(value, dict):
                                            await self._on_ohlcv({
                                                "instrument": instr,
                                                "exchange": exchange,
                                                "interval": "minute",
                                                "open": value.get("open", 0.0),
                                                "high": value.get("high", 0.0),
                                                "low": value.get("low", 0.0),
                                                "close": value.get("close", 0.0),
                                                "volume": value.get("volume", 0),
                                            })
                            except GrowwAPIError as e:
                                logger.debug("OHLC fetch skipped for %s: %s", sym, e)

            except GrowwAPIError as e:
                logger.error("Groww poll error: %s", e)
            except Exception as e:
                logger.error("Poll error: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def get_historical(
        self,
        tradingsymbol: str,
        interval_minutes: int = 1,
        days: int = 7,
        exchange: str = "NSE",
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        start = now - timedelta(days=days)
        result = await self._client.get_historical_candles(
            trading_symbol=tradingsymbol,
            start_time=start.strftime("%Y-%m-%dT%H:%M:%S"),
            end_time=now.strftime("%Y-%m-%dT%H:%M:%S"),
            exchange=exchange,
            interval_in_minutes=str(interval_minutes),
        )
        candles = result.get("payload", {}).get("candles", result.get("candles", []))
        parsed = []
        for c in candles:
            if isinstance(c, dict):
                parsed.append(c)
            elif isinstance(c, list) and len(c) >= 6:
                parsed.append({
                    "timestamp": c[0],
                    "open": c[1],
                    "high": c[2],
                    "low": c[3],
                    "close": c[4],
                    "volume": c[5],
                })
        return parsed
