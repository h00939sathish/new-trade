import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.connectors.jugaad.client import JugaadClient

logger = logging.getLogger("connector.jugaad.market_data")


class JugaadMarketDataProvider:
    def __init__(
        self,
        client: JugaadClient | None = None,
        on_tick: Callable | None = None,
        on_ohlcv: Callable | None = None,
    ):
        self._client = client or JugaadClient()
        self._on_tick = on_tick
        self._on_ohlcv = on_ohlcv
        self._instruments: list[str] = []
        self._exchange = "NSE"
        self._running = False
        self._task: asyncio.Task | None = None

    def set_tick_callback(self, callback: Callable) -> None:
        self._on_tick = callback

    def set_ohlcv_callback(self, callback: Callable) -> None:
        self._on_ohlcv = callback

    def add_instrument(self, tradingsymbol: str, exchange: str = "NSE") -> None:
        if tradingsymbol not in self._instruments:
            self._instruments.append(tradingsymbol)
            logger.info("Jugaad added instrument: %s", tradingsymbol)

    def remove_instrument(self, tradingsymbol: str) -> None:
        self._instruments = [i for i in self._instruments if i != tradingsymbol]

    async def start(self, poll_interval: float = 60.0) -> None:
        if self._running:
            return
        self._running = True
        await self._client.connect()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Jugaad market data started (uses NSE bhavcopy)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._client.disconnect()
        logger.info("Jugaad market data stopped")

    async def get_historical(
        self,
        tradingsymbol: str,
        interval_minutes: int = 1440,
        days: int = 30,
        exchange: str = "NSE",
    ) -> list[dict[str, Any]]:
        now = date.today()
        from_date = now - timedelta(days=days)
        return await self._client.get_historical(
            symbol=tradingsymbol,
            from_date=from_date,
            to_date=now,
        )

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                if not self._instruments:
                    await asyncio.sleep(5)
                    continue

                now_utc = datetime.now(UTC)
                ist_hour = (now_utc.hour + 5) % 24
                ist_min = (now_utc.minute + 30) % 60
                is_market_hours = 9 <= ist_hour < 15 or (ist_hour == 15 and ist_min <= 30)

                if not is_market_hours:
                    await asyncio.sleep(60)
                    continue

                await asyncio.sleep(60)
            except Exception as e:
                logger.error("Jugaad poll error: %s", e)
                await asyncio.sleep(10)

    async def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        return {}
