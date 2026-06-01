import logging
import math
import random
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

logger = logging.getLogger("connector.backtest_provider")

TICKS_PER_CANDLE = 375
TRADING_START_HOUR = 9
TRADING_START_MINUTE = 15
TRADING_END_HOUR = 15
TRADING_END_MINUTE = 30


class BacktestDataProvider:
    def __init__(
        self,
        market_data_provider: Any,
        instruments: list[str] | None = None,
        exchange: str = "NSE",
        on_progress: Callable[[str], None] | None = None,
    ):
        self._provider = market_data_provider
        self._instruments = instruments or []
        self._exchange = exchange
        self._on_progress = on_progress

    def add_instrument(self, instrument: str) -> None:
        if instrument not in self._instruments:
            self._instruments.append(instrument)

    async def get_backtest_ticks(
        self,
        instruments: list[str] | None = None,
        days: int = 60,
    ) -> list[dict[str, Any]]:
        targets = instruments or self._instruments
        if not targets:
            logger.warning("No instruments configured for backtest data")
            return generate_synthetic_ticks()

        now = date.today()
        from_date = now - timedelta(days=days)

        all_ticks: list[dict[str, Any]] = []
        for inst in targets:
            try:
                candles = await self._fetch_daily_candles(inst, from_date, now)
                if not candles:
                    continue
                ticks = self._expand_candles_to_ticks(inst, candles)
                all_ticks.extend(ticks)
                logger.info(
                    "Backtest data: %s -> %d candles, %d ticks",
                    inst, len(candles), len(ticks),
                )
                if self._on_progress:
                    self._on_progress(inst)
            except Exception as e:
                logger.warning("Failed to fetch backtest data for %s: %s", inst, e)

        if not all_ticks:
            logger.warning("No backtest data from provider — using synthetic")
            return generate_synthetic_ticks()

        all_ticks.sort(key=lambda t: t.get("timestamp", 0))
        return all_ticks

    async def _fetch_daily_candles(
        self,
        instrument: str,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, Any]]:
        candles = []
        if hasattr(self._provider, "get_historical"):
            try:
                candles = await self._provider.get_historical(
                    tradingsymbol=instrument,
                    interval_minutes=1440,
                    days=(to_date - from_date).days,
                    exchange=self._exchange,
                )
            except Exception as e:
                logger.warning("Primary provider get_historical failed for %s: %s", instrument, e)

        if not candles:
            # Fallback to Jugaad for real data instead of synthetic
            logger.info("Falling back to JugaadMarketDataProvider for %s historical data", instrument)
            try:
                from src.connectors.jugaad.market_data import JugaadMarketDataProvider
                jugaad_provider = JugaadMarketDataProvider()
                candles = await jugaad_provider.get_historical(
                    tradingsymbol=instrument,
                    interval_minutes=1440,
                    days=(to_date - from_date).days,
                    exchange=self._exchange,
                )
            except Exception as e:
                logger.warning("Jugaad fallback failed for %s: %s", instrument, e)

        return candles

    def _expand_candles_to_ticks(
        self,
        instrument: str,
        candles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ticks: list[dict[str, Any]] = []
        random.seed(hash(instrument) & 0xFFFFFFFF)

        for ci, candle in enumerate(candles):
            o = candle.get("open", 0)
            h = candle.get("high", o)
            low_val = candle.get("low", o)
            close_val = candle.get("close", o)
            volume = candle.get("volume", 10000)

            ts = candle.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    ts = datetime.now(UTC)
            if isinstance(ts, datetime):
                ts = ts.replace(
                    hour=TRADING_START_HOUR,
                    minute=TRADING_START_MINUTE,
                    second=0, microsecond=0,
                )
            else:
                base_dt = datetime.now(UTC) - timedelta(days=len(candles) - ci)
                ts = base_dt.replace(
                    hour=TRADING_START_HOUR,
                    minute=TRADING_START_MINUTE,
                    second=0, microsecond=0,
                )

            candles_ticks = []
            for ti in range(TICKS_PER_CANDLE):
                progress = ti / TICKS_PER_CANDLE
                smooth_price = o + (close_val - o) * progress
                wiggle = h - low_val
                noise = random.gauss(0, wiggle * 0.15) if wiggle > 0 else 0
                tick_price = max(smooth_price + noise, 0.01)

                volume_chunk = max(1, volume // TICKS_PER_CANDLE)
                tick_ts = ts + timedelta(seconds=int(progress * 6 * 3600))

                candles_ticks.append({
                    "instrument": instrument,
                    "exchange": self._exchange,
                    "price": round(tick_price, 2),
                    "volume": volume_chunk + random.randint(-5, 5),
                    "timestamp": tick_ts.isoformat(),
                })

            ticks.extend(candles_ticks)

        return ticks

    async def get_historical(
        self,
        tradingsymbol: str,
        interval_minutes: int = 1440,
        days: int = 30,
        exchange: str = "NSE",
    ) -> list[dict[str, Any]]:
        if hasattr(self._provider, "get_historical"):
            return await self._provider.get_historical(
                tradingsymbol=tradingsymbol,
                interval_minutes=interval_minutes,
                days=days,
                exchange=exchange,
            )
        return []


def generate_synthetic_ticks(n: int = 5000) -> list[dict[str, Any]]:
    from datetime import UTC, datetime, timedelta
    base_time = datetime(2026, 5, 25, 9, 15, 0, tzinfo=UTC)
    ticks = []
    price = 100.0
    for i in range(n):
        phase = math.sin(i / 50) * 2
        noise = (i % 7 - 3) * 0.1
        price += phase * 0.1 + noise
        price = max(price, 10.0)
        ticks.append({
            "instrument": "TEST",
            "exchange": "NSE",
            "price": round(price, 2),
            "volume": 1000 + i % 5000,
            "timestamp": base_time + timedelta(seconds=i),
        })
    return ticks
