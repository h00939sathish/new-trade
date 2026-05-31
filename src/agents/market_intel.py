from collections import defaultdict
from typing import Any

from src.agents.base import BaseAgent
from src.schemas.events import (
    Event,
    EventType,
    Exchange,
    OHLCVEvent,
    TickEvent,
)
from src.utils.timeframe import HIGHER_TIMEFRAMES, aggregate_candles, timeframe_to_minutes


class MarketIntelAgent(BaseAgent):
    def __init__(self, event_store=None, market_data_provider: Any = None):
        super().__init__("market_intel", event_store=event_store)
        self._instruments: list[str] = []
        self._exchange: Exchange = Exchange.NSE
        self._latest_ticks: dict[str, TickEvent] = {}
        self._latest_ohlcv: dict[str, OHLCVEvent] = {}
        self._market_data_provider: Any = market_data_provider
        self._candle_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._max_buffer_size = 500

    async def on_start(self) -> None:
        provider_name = type(self._market_data_provider).__name__ if self._market_data_provider else "None"
        self.logger.info(
            "Market Intelligence Agent initializing (provider=%s, instruments=%d)",
            provider_name,
            len(self._instruments),
        )
        self.subscribe_market_data()
        self.subscribe_system()
        if self._market_data_provider is not None:
            self._market_data_provider.set_tick_callback(self._on_provider_tick)
            self._market_data_provider.set_ohlcv_callback(self._on_provider_ohlcv)
            for inst in self._instruments:
                self._market_data_provider.add_instrument(inst, self._exchange.value)
            await self._market_data_provider.start()
            await self._load_historical_data()
        else:
            self.logger.warning("No market data provider configured — agent will be passive")
        self._emit_market_data()

    def add_instrument(self, instrument: str) -> None:
        if instrument not in self._instruments:
            self._instruments.append(instrument)

    def set_exchange(self, exchange: Exchange) -> None:
        self._exchange = exchange

    def get_latest_tick(self, instrument: str) -> TickEvent | None:
        return self._latest_ticks.get(instrument)

    def get_latest_ohlcv(self, instrument: str, interval: str = "minute") -> OHLCVEvent | None:
        key = f"{instrument}.{interval}"
        return self._latest_ohlcv.get(key)

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.TICK:
                self._handle_tick(event)
            case EventType.OHLCV:
                self._handle_ohlcv(event)
            case EventType.SYSTEM_HEALTH:
                self.logger.debug("System health: %s", event.data)

    async def ingest_tick(
        self,
        instrument: str,
        exchange: Exchange,
        last_price: float,
        volume: int | None = None,
        bid: float | None = None,
        ask: float | None = None,
    ) -> None:
        event = TickEvent.create(
            instrument=instrument,
            exchange=exchange,
            last_price=last_price,
            volume=volume,
            bid=bid,
            ask=ask,
            producer=self.name,
        )
        self._latest_ticks[instrument] = event
        await self.emit(event)

    async def ingest_ohlcv(
        self,
        instrument: str,
        exchange: Exchange,
        interval: str,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        oi: float | None = None,
    ) -> None:
        event = OHLCVEvent.create(
            instrument=instrument,
            exchange=exchange,
            interval=interval,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            oi=oi,
            producer=self.name,
        )
        key = f"{instrument}.{interval}"
        self._latest_ohlcv[key] = event
        await self.emit(event)

        # Only buffer and aggregate from base timeframe to prevent recursive aggregation cascade
        if interval in ("minute", "1minute"):
            buf_key = f"{instrument}.{interval}"
            buf = self._candle_buffer[buf_key]
            buf.append({
                "timestamp": event.timestamp,
                "open": open,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            })
            if len(buf) > self._max_buffer_size:
                buf.pop(0)
            await self._aggregate_from_buffer(instrument, exchange, interval)

    async def _aggregate_from_buffer(
        self,
        instrument: str,
        exchange: Exchange,
        interval: str,
    ) -> None:
        source_min = timeframe_to_minutes(interval)
        buf_key = f"{instrument}.{interval}"
        buf = self._candle_buffer[buf_key]

        for tf, tf_min in HIGHER_TIMEFRAMES.items():
            if tf_min <= source_min:
                continue
            n_candles = tf_min // source_min
            # Fix: Aggregate only when the timeframe boundary closes
            if len(buf) % n_candles != 0:
                continue
            recent = buf[-n_candles:]
            result = aggregate_candles(interval, recent)
            tf_candles = result.get(tf, [])
            if not tf_candles:
                continue
            agg = tf_candles[-1]

            # Emit aggregated candles directly instead of calling ingest_ohlcv recursively
            from datetime import UTC, datetime
            dt = datetime.fromtimestamp(agg["timestamp"], UTC)
            agg_event = OHLCVEvent.create(
                instrument=instrument,
                exchange=exchange,
                interval=tf,
                open=agg["open"],
                high=agg["high"],
                low=agg["low"],
                close=agg["close"],
                volume=agg["volume"],
                producer=self.name,
            )
            # Override event timestamp with rounded timeframe timestamp
            agg_event.timestamp = dt
            agg_event.data["timestamp"] = dt.isoformat()

            key = f"{instrument}.{tf}"
            self._latest_ohlcv[key] = agg_event
            await self.emit(agg_event)

    async def on_stop(self) -> None:
        if self._market_data_provider is not None:
            await self._market_data_provider.stop()
        self.logger.info("Market Intelligence Agent stopping")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "instruments": len(self._instruments),
            "latest_ticks": len(self._latest_ticks),
            "latest_ohlcv": len(self._latest_ohlcv),
            "live_data": self._market_data_provider is not None,
        })
        return base

    def _handle_tick(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        # Store the event as-is — downstream should access via .data dict
        # to avoid type mismatch between Event and TickEvent
        if isinstance(event, TickEvent):
            self._latest_ticks[instrument] = event
        else:
            # Convert generic Event to TickEvent for consistent downstream access
            try:
                tick = TickEvent(**event.model_dump())
                self._latest_ticks[instrument] = tick
            except Exception:
                self._latest_ticks[instrument] = event

    def _handle_ohlcv(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        interval = event.data.get("interval", "minute")
        key = f"{instrument}.{interval}"
        self._latest_ohlcv[key] = event

    async def _on_provider_tick(self, data: dict[str, Any]) -> None:
        self.logger.debug(
            "Tick received: %s @ %.2f (vol=%s)",
            data.get("instrument"),
            data.get("last_price", 0),
            data.get("volume"),
        )
        await self.ingest_tick(
            instrument=data["instrument"],
            exchange=Exchange(data["exchange"]),
            last_price=data["last_price"],
            volume=data.get("volume"),
        )

    async def _on_provider_ohlcv(self, data: dict[str, Any]) -> None:
        self.logger.debug(
            "OHLCV received: %s [%s] O=%.2f H=%.2f L=%.2f C=%.2f V=%s",
            data.get("instrument"),
            data.get("interval", "minute"),
            data.get("open", 0),
            data.get("high", 0),
            data.get("low", 0),
            data.get("close", 0),
            data.get("volume", 0),
        )
        await self.ingest_ohlcv(
            instrument=data["instrument"],
            exchange=Exchange(data["exchange"]),
            interval=data.get("interval", "minute"),
            open=data.get("open", 0.0),
            high=data.get("high", 0.0),
            low=data.get("low", 0.0),
            close=data.get("close", 0.0),
            volume=data.get("volume", 0),
        )

    async def _load_historical_data(self) -> None:
        if not hasattr(self._market_data_provider, "get_historical"):
            return
        for inst in self._instruments:
            try:
                candles = await self._market_data_provider.get_historical(
                    tradingsymbol=inst,
                    interval_minutes=1440,
                    days=30,
                    exchange=self._exchange.value,
                )
                self.logger.info("Loaded %d daily candles for %s", len(candles), inst)
                for c in candles[-60:]:
                    await self.ingest_ohlcv(
                        instrument=inst,
                        exchange=self._exchange,
                        interval="day",
                        open=c["open"],
                        high=c["high"],
                        low=c["low"],
                        close=c["close"],
                        volume=c.get("volume", 0),
                    )
            except Exception as e:
                self.logger.warning("Failed to load historical data for %s: %s", inst, e)

    def _emit_market_data(self) -> None:
        pass


class MarketIntelAgentBuilder:
    def __init__(self):
        self._agent = MarketIntelAgent()

    def with_instrument(self, instrument: str) -> "MarketIntelAgentBuilder":
        self._agent.add_instrument(instrument)
        return self

    def with_exchange(self, exchange: Exchange) -> "MarketIntelAgentBuilder":
        self._agent.set_exchange(exchange)
        return self

    def with_instruments(self, instruments: list[str]) -> "MarketIntelAgentBuilder":
        for inst in instruments:
            self._agent.add_instrument(inst)
        return self

    def build(self) -> MarketIntelAgent:
        return self._agent
