import json
import logging
import math
from pathlib import Path
import random
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
import httpx

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
        days: int = 7,
    ) -> list[dict[str, Any]]:
        targets = instruments or self._instruments
        if not targets:
            logger.warning("No instruments configured for backtest data")
            return generate_synthetic_ticks()

        all_ticks: list[dict[str, Any]] = []
        cache_dir = Path("data/historical")
        cache_dir.mkdir(parents=True, exist_ok=True)

        for inst in targets:
            cache_file = cache_dir / f"{inst}_1m_{days}d.json"
            candles = None
            if days <= 30:
                if cache_file.exists():
                    try:
                        with cache_file.open("r") as f:
                            candles = json.load(f)
                        logger.info("Loaded cached 1m candles for %s", inst)
                    except Exception as e:
                        logger.warning("Failed to load cache for %s: %s", inst, e)

                if not candles:
                    logger.info("Fetching real 1m candles for %s from Yahoo Finance...", inst)
                    candles = await fetch_historical_1m_candles(inst, self._exchange, days)
                    if candles:
                        try:
                            with cache_file.open("w") as f:
                                json.dump(candles, f)
                        except Exception as e:
                            logger.warning("Failed to save cache for %s: %s", inst, e)
            else:
                logger.info("days=%d > 30, skipping Yahoo 1m fetch for %s to trigger daily fallback", days, inst)

            if candles:
                ticks = []
                for c in candles:
                    ticks.append({
                        "instrument": inst,
                        "exchange": self._exchange,
                        "price": round(c["close"], 2),
                        "volume": int(c["volume"]),
                        "timestamp": c["timestamp"],
                    })
                all_ticks.extend(ticks)
                logger.info(
                    "Backtest data: %s -> %d real 1m ticks",
                    inst, len(ticks),
                )
                if self._on_progress:
                    self._on_progress(inst)

        if not all_ticks:
            logger.warning("No historical 1m data available — falling back to daily candle expansion")
            now = date.today()
            from_date = now - timedelta(days=days)
            for inst in targets:
                try:
                    candles = await self._fetch_daily_candles(inst, from_date, now)
                    if not candles:
                        continue
                    ticks = self._expand_candles_to_ticks(inst, candles)
                    all_ticks.extend(ticks)
                    logger.info(
                        "Fallback backtest data: %s -> %d candles, %d ticks",
                        inst, len(candles), len(ticks),
                    )
                except Exception as e:
                    logger.warning("Failed fallback fetch for %s: %s", inst, e)

        if not all_ticks:
            logger.warning("No backtest data from provider — using synthetic")
            return generate_synthetic_ticks()

        # Check coverage
        expected_candles = (days * 252 / 365) * 375
        for inst in targets:
            inst_ticks = [t for t in all_ticks if t["instrument"] == inst]
            coverage = len(inst_ticks) / expected_candles if expected_candles > 0 else 0
            if coverage < 0.95:
                logger.error(
                    "Backtest Aborted: %s coverage is %.1f%% (%d / %d candles). Missing data detected.",
                    inst, coverage * 100, len(inst_ticks), expected_candles
                )
                raise ValueError(
                    f"BACKTEST ABORTED: Insufficient 1m data coverage for {inst} ({coverage:.1%}). "
                    f"Yahoo Finance retention limit or API error."
                )

        all_ticks.sort(key=lambda t: t.get("timestamp", ""))
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


async def fetch_historical_1m_candles(
    symbol: str, exchange: str = "NSE", days: int = 7
) -> list[dict[str, Any]]:
    """Fetch real 1-minute historical candles from Yahoo Finance.

    Yahoo only allows up to ~30 days of 1m data per request,
    so we split into 30-day chunks and merge.
    """
    exchange_map = {"NSE": ".NS", "BSE": ".BO"}
    suffix = exchange_map.get(exchange, "")
    max_chunk_days = 8
    candles: list[dict[str, Any]] = []

    async def _fetch_range(start_day: int, end_day: int) -> list[dict[str, Any]]:
        r = max(2, end_day - start_day)
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{symbol}{suffix}?period1={start_day}&period2={end_day}&interval=1m"
        )
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            timestamps = result.get("timestamp", [])
            indicators = result.get("indicators", {}).get("quote", [{}])[0]
            opens = indicators.get("open", [])
            highs = indicators.get("high", [])
            lows = indicators.get("low", [])
            closes = indicators.get("close", [])
            volumes = indicators.get("volume", [])

            out: list[dict[str, Any]] = []
            for i, ts in enumerate(timestamps):
                if opens[i] is None or closes[i] is None:
                    continue
                out.append(
                    {
                        "timestamp": datetime.fromtimestamp(ts, UTC).isoformat(),
                        "open": float(opens[i]),
                        "high": float(highs[i]) if highs[i] is not None else float(closes[i]),
                        "low": float(lows[i]) if lows[i] is not None else float(closes[i]),
                        "close": float(closes[i]),
                        "volume": float(volumes[i]) if volumes[i] is not None else 0.0,
                    }
                )
            return out

    import time as _time
    now_ts = int(_time.time())
    if days <= max_chunk_days:
        candles = await _fetch_range(now_ts - days * 86400, now_ts)
    else:
        # Work backwards from today in 30-day windows
        end = now_ts
        remaining = days
        while remaining > 0 and end > 0:
            chunk = min(remaining, max_chunk_days)
            start = end - chunk * 86400
            try:
                chunk_candles = await _fetch_range(start, end)
                candles = chunk_candles + candles  # prepend so oldest-first
            except Exception as e:
                logger.warning("Yahoo chunk fetch failed for %s %d-%dd: %s", symbol, days - remaining, days, e)
            remaining -= chunk
            end = start

    return candles


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
