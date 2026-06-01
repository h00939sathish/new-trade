import logging
from collections import deque
from typing import Any

import numpy as np

from src.agents.base import BaseAgent
from src.schemas.events import Event, EventType

logger = logging.getLogger("agent.regime")

class RegimeDetectionAgent(BaseAgent):
    def __init__(self, event_store=None, window: int = 14):
        super().__init__(name="regime_detection", event_store=event_store)
        self._window = window
        self._prices: dict[str, deque[float]] = {}
        self._highs: dict[str, deque[float]] = {}
        self._lows: dict[str, deque[float]] = {}
        self._current_regime: str = "mean_reverting"

    async def on_start(self) -> None:
        self.logger.info("Regime Detection Agent starting")
        self.subscribe(EventType.OHLCV)

        # Broadcast initial regime so StrategyGenAgent doesn't default to
        # wrong weights after a restart (T8 fix from plan.md)
        from src.schemas.events import Event, EventMetadata
        initial_regime_event = Event(
            event_type=EventType.SYSTEM_STATE,
            stream="system.state",
            data={"regime": self._current_regime, "instrument": "__startup__"},
            metadata=EventMetadata(producer=self.name),
        )
        await self.emit(initial_regime_event)
        self.logger.info("Broadcast initial regime: %s", self._current_regime)

    async def on_stop(self) -> None:
        self.logger.info("Regime Detection Agent stopping")

    async def on_event(self, event: Event) -> None:
        if event.event_type == EventType.OHLCV:
            await self._process_ohlcv(event)

    async def _process_ohlcv(self, event: Event) -> None:
        data = event.data
        instrument = data.get("instrument", "")
        close = data.get("close")
        high = data.get("high", close)
        low = data.get("low", close)
        if close is None:
            return

        self._prices.setdefault(instrument, deque(maxlen=100)).append(float(close))
        self._highs.setdefault(instrument, deque(maxlen=100)).append(float(high))
        self._lows.setdefault(instrument, deque(maxlen=100)).append(float(low))

        prices = list(self._prices[instrument])
        if len(prices) < self._window + 1:
            return

        highs = list(self._highs[instrument])
        lows = list(self._lows[instrument])

        # 1. Moving Average (SMA)
        sma = np.mean(prices[-self._window:])
        current_price = close

        # 2. Average True Range (ATR)
        trs = []
        for j in range(1, len(prices)):
            closes_prev = prices[j-1]
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - closes_prev),
                abs(lows[j] - closes_prev)
            )
            trs.append(tr)

        atr = np.mean(trs[-self._window:]) if trs else 0.0
        atr_ma = np.mean(trs[-self._window*2:]) if len(trs) >= self._window*2 else atr

        # 3. Trend strength (ADX / DX equivalent)
        trend_strength = self._compute_trend_strength(highs, lows, prices, self._window)

        # 4. Classify regime
        new_regime = "mean_reverting"
        if atr_ma > 0 and atr > atr_ma * 1.5:
            new_regime = "high_volatility"
        elif trend_strength > 25:
            if current_price > sma:
                new_regime = "trending_up"
            else:
                new_regime = "trending_down"
        else:
            new_regime = "mean_reverting"

        if new_regime != self._current_regime:
            self._current_regime = new_regime
            self.logger.warning("Market regime changed to: %s", new_regime)

            from src.schemas.events import Event, EventMetadata
            regime_event = Event(
                event_type=EventType.SYSTEM_STATE,
                stream="system.state",
                data={"regime": new_regime, "instrument": instrument},
                metadata=EventMetadata(producer=self.name),
            )
            await self.emit(regime_event)

    def _compute_trend_strength(self, highs: list[float], lows: list[float], closes: list[float], period: int) -> float:
        if len(closes) < period + 1:
            return 0.0

        plus_dm = []
        minus_dm = []
        tr = []

        for i in range(1, len(closes)):
            up = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]

            p_dm = up if (up > down and up > 0) else 0.0
            m_dm = down if (down > up and down > 0) else 0.0

            plus_dm.append(p_dm)
            minus_dm.append(m_dm)

            true_range = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr.append(true_range)

        smooth_tr = sum(tr[-period:])
        if smooth_tr == 0:
            return 0.0

        smooth_plus = sum(plus_dm[-period:])
        smooth_minus = sum(minus_dm[-period:])

        plus_di = 100 * smooth_plus / smooth_tr
        minus_di = 100 * smooth_minus / smooth_tr

        denom = plus_di + minus_di
        if denom == 0:
            return 0.0

        dx = 100 * abs(plus_di - minus_di) / denom
        return dx

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "current_regime": self._current_regime,
            "tracked_instruments": list(self._prices.keys()),
        })
        return base
