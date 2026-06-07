import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from src.connectors.jugaad.client import JugaadClient

logger = logging.getLogger("connector.jugaad.market_data")

# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))


class JugaadMarketDataProvider:
    """Market data provider that uses Jugaad for historical NSE data
    and Yahoo Finance for live price polling."""

    def __init__(
        self,
        client: JugaadClient | None = None,
        on_tick: Callable | None = None,
        on_ohlcv: Callable | None = None,
        poll_interval: float | None = None,
        market_hours_only: bool | None = None,
    ):
        self._client = client or JugaadClient()
        self._on_tick = on_tick
        self._on_ohlcv = on_ohlcv
        self._instruments: list[str] = []
        self._exchange = "NSE"
        self._running = False
        self._task: asyncio.Task | None = None

        # Configurable via constructor or settings
        from src.config.settings import settings

        self._poll_interval = poll_interval or getattr(settings, "yahoo_poll_interval", 60)
        self._market_hours_only = (
            market_hours_only
            if market_hours_only is not None
            else getattr(settings, "market_hours_only", True)
        )

        # Synthetic candle accumulation: instrument -> list of tick prices within current minute
        self._minute_ticks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._last_candle_minute: dict[str, int] = {}

    def set_tick_callback(self, callback: Callable) -> None:
        self._on_tick = callback

    def set_ohlcv_callback(self, callback: Callable) -> None:
        self._on_ohlcv = callback

    def add_instrument(self, tradingsymbol: str, exchange: str = "NSE") -> None:
        if tradingsymbol not in self._instruments:
            self._instruments.append(tradingsymbol)
            logger.info("Added instrument: %s (exchange=%s)", tradingsymbol, exchange)

    def remove_instrument(self, tradingsymbol: str) -> None:
        self._instruments = [i for i in self._instruments if i != tradingsymbol]

    async def start(self, poll_interval: float | None = None) -> None:
        if self._running:
            return
        if poll_interval is not None:
            self._poll_interval = poll_interval
        self._running = True
        await self._client.connect()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Jugaad+Yahoo market data started (poll_interval=%ds, market_hours_only=%s, instruments=%d)",
            self._poll_interval,
            self._market_hours_only,
            len(self._instruments),
        )

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
        logger.info("Jugaad+Yahoo market data stopped")

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

    async def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        """Get live last traded prices via Yahoo Finance."""
        try:
            from src.connectors.yahoo import get_ltp_yahoo

            result = await get_ltp_yahoo(instruments)
            return result
        except Exception as e:
            logger.warning("Yahoo LTP fetch failed: %s", e)
            return {}

    # ──────────────────────────────────────────────
    # Core polling loop
    # ──────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Poll Yahoo Finance for live prices and emit tick/OHLCV events."""
        logger.info("Poll loop started, waiting for first cycle...")

        # Small initial delay to let the system fully boot
        await asyncio.sleep(3)

        while self._running:
            try:
                if not self._instruments:
                    logger.debug("No instruments subscribed, waiting...")
                    await asyncio.sleep(5)
                    continue

                # Check market hours (IST 9:15 - 15:30)
                if self._market_hours_only and not self._is_market_hours():
                    now_ist = datetime.now(IST)
                    logger.debug(
                        "Outside market hours (IST %s), sleeping 60s",
                        now_ist.strftime("%H:%M"),
                    )
                    await asyncio.sleep(60)
                    continue

                # Fetch live prices from Yahoo Finance
                await self._fetch_and_emit()

                # Sleep for the configured interval
                await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Poll loop error: %s", e, exc_info=True)
                await asyncio.sleep(10)

        logger.info("Poll loop exited")

    async def _fetch_and_emit(self) -> None:
        """Fetch prices from Yahoo Finance and emit tick + OHLCV events."""
        from src.connectors.yahoo import get_ltp_yahoo

        # Build Yahoo-compatible instrument list (e.g., "NSE:RELIANCE")
        yahoo_instruments = [f"{self._exchange}:{inst}" for inst in self._instruments]

        try:
            quotes = await get_ltp_yahoo(yahoo_instruments)
        except Exception as e:
            logger.warning("Yahoo Finance fetch failed: %s", e)
            return

        if not quotes:
            logger.warning("Yahoo Finance returned no data for %s", self._instruments)
            return

        fetched_count = 0
        now = datetime.now(UTC)
        current_minute = now.minute

        for inst in self._instruments:
            key = f"{self._exchange}:{inst}"
            quote = quotes.get(key)
            if not quote or quote.get("last_price") is None:
                continue

            fetched_count += 1
            price = float(quote["last_price"])
            volume = int(quote.get("volume") or 0)

            # ── Emit tick event ──
            if self._on_tick is not None:
                try:
                    await self._on_tick(
                        {
                            "instrument": inst,
                            "exchange": self._exchange,
                            "last_price": price,
                            "volume": volume,
                        }
                    )
                except Exception as e:
                    logger.error("Tick callback error for %s: %s", inst, e)

            # ── Accumulate for synthetic candle ──
            self._minute_ticks[inst].append(
                {
                    "price": price,
                    "volume": volume,
                    "time": now,
                }
            )

            # Emit a synthetic 1-minute OHLCV candle when the minute rolls over
            last_min = self._last_candle_minute.get(inst)
            if last_min is not None and last_min != current_minute:
                await self._emit_synthetic_candle(inst)

            self._last_candle_minute[inst] = current_minute

        logger.info(
            "Yahoo LTP fetched for %d/%d instruments",
            fetched_count,
            len(self._instruments),
        )

    async def _emit_synthetic_candle(self, instrument: str) -> None:
        """Build and emit a synthetic 1-minute OHLCV candle from accumulated ticks."""
        ticks = self._minute_ticks.pop(instrument, [])
        if not ticks:
            return

        prices = [t["price"] for t in ticks]
        volumes = [t["volume"] for t in ticks]

        candle_data = {
            "instrument": instrument,
            "exchange": self._exchange,
            "interval": "minute",
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(volumes),
        }

        if self._on_ohlcv is not None:
            try:
                await self._on_ohlcv(candle_data)
                logger.debug(
                    "Emitted synthetic candle for %s: O=%.2f H=%.2f L=%.2f C=%.2f",
                    instrument,
                    candle_data["open"],
                    candle_data["high"],
                    candle_data["low"],
                    candle_data["close"],
                )
            except Exception as e:
                logger.error("OHLCV callback error for %s: %s", instrument, e)

    @staticmethod
    def _is_market_hours() -> bool:
        """Check if current time is within NSE market hours (IST 9:15 - 15:30)."""
        now_ist = datetime.now(IST)
        market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now_ist <= market_close
