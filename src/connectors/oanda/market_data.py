import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)


class OandaMarketDataProvider:
    def __init__(
        self,
        client: Any | None = None,
        on_tick: Callable | None = None,
        on_ohlcv: Callable | None = None,
    ):
        self._client = client
        self._on_tick = on_tick
        self._on_ohlcv = on_ohlcv
        self._instruments: list[str] = []
        self._exchange_map: dict[str, str] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._last_candle_time: dict[str, str] = {}
        self._candle_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def set_tick_callback(self, callback: Callable) -> None:
        self._on_tick = callback

    def set_ohlcv_callback(self, callback: Callable) -> None:
        self._on_ohlcv = callback

    def add_instrument(self, tradingsymbol: str, exchange: str = "FX") -> None:
        if tradingsymbol not in self._instruments:
            self._instruments.append(tradingsymbol)
            self._exchange_map[tradingsymbol] = exchange

    def remove_instrument(self, tradingsymbol: str) -> None:
        if tradingsymbol in self._instruments:
            self._instruments.remove(tradingsymbol)
            self._exchange_map.pop(tradingsymbol, None)

    async def start(self, poll_interval: float = 1.0) -> None:
        if self._running:
            return
        if not self._client:
            logger.warning("OANDA market data provider: no client configured")
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._backfill_and_stream()),
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _backfill_and_stream(self) -> None:
        try:
            await self._backfill_historical()
        except Exception as e:
            logger.warning("OANDA historical backfill failed: %s", e)
        await self._stream_pricing()

    async def _backfill_historical(self) -> None:
        for instrument in self._instruments:
            try:
                candles = self._client.get_candles(instrument, granularity="M1", count=500)
                for c in candles:
                    ohlcv = self._parse_candle(instrument, c)
                    if ohlcv and self._on_ohlcv:
                        if asyncio.iscoroutinefunction(self._on_ohlcv):
                            await self._on_ohlcv(ohlcv)
                        else:
                            self._on_ohlcv(ohlcv)
                    ts = c.get("time", "")
                    if ts:
                        self._last_candle_time[instrument] = ts
                logger.info("Backfilled %d M1 candles for %s", len(candles), instrument)
            except Exception as e:
                logger.error("Failed to backfill %s: %s", instrument, e)

    async def _stream_pricing(self) -> None:
        if not self._instruments:
            return
        try:
            async for tick in self._client.stream_pricing(self._instruments):
                if not self._running:
                    break
                await self._process_pricing_tick(tick)
        except Exception as e:
            logger.error("Pricing stream error: %s", e)

    async def _process_pricing_tick(self, tick: dict[str, Any]) -> None:
        tick_type = tick.get("type")
        if tick_type == "PRICE":
            instrument = tick.get("instrument", "")
            if instrument not in self._instruments:
                return
            bid = float(tick.get("bids", [{}])[0].get("price", 0)) if tick.get("bids") else None
            ask = float(tick.get("asks", [{}])[0].get("price", 0)) if tick.get("asks") else None
            midpoint = (bid + ask) / 2 if bid and ask else None
            ts_str = tick.get("time", "")
            if self._on_tick:
                payload = {
                    "instrument": instrument,
                    "exchange": self._exchange_map.get(instrument, "FX"),
                    "last_price": midpoint or 0,
                    "bid": bid,
                    "ask": ask,
                    "spread": round(ask - bid, 5) if bid and ask else None,
                    "timestamp": ts_str,
                }
                if asyncio.iscoroutinefunction(self._on_tick):
                    await self._on_tick(payload)
                else:
                    self._on_tick(payload)
        elif tick_type == "HEARTBEAT":
            logger.debug("OANDA pricing heartbeat: %s", tick.get("time", ""))

    def _parse_candle(self, instrument: str, candle: dict[str, Any]) -> dict[str, Any] | None:
        mid = candle.get("mid", {})
        o = mid.get("o")
        h = mid.get("h")
        lo = mid.get("l")
        c = mid.get("c")
        v = candle.get("volume", 0)
        ts = candle.get("time", "")
        if not all([o, h, lo, c]):
            return None
        return {
            "instrument": instrument,
            "exchange": self._exchange_map.get(instrument, "FX"),
            "open": float(o),
            "high": float(h),
            "low": float(lo),
            "close": float(c),
            "volume": float(v),
            "timestamp": ts,
        }

    async def get_historical(
        self,
        tradingsymbol: str,
        interval_minutes: int = 1,
        days: int = 7,
        exchange: str = "FX",
    ) -> list[dict[str, Any]]:
        if not self._client:
            return []
        granularity = self._minutes_to_granularity(interval_minutes)
        to_time = datetime.now(UTC)
        from_time = to_time - timedelta(days=days)
        candles = self._client.get_candles(
            tradingsymbol, granularity=granularity, count=5000,
            from_time=from_time.isoformat().replace("+00:00", "Z"),
            to_time=to_time.isoformat().replace("+00:00", "Z"),
        )
        result = []
        for c in candles:
            parsed = self._parse_candle(tradingsymbol, c)
            if parsed:
                result.append(parsed)
        return result

    @staticmethod
    def _minutes_to_granularity(minutes: int) -> str:
        mapping = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 120: "H2", 240: "H4", 1440: "D"}
        return mapping.get(minutes, "M1")
