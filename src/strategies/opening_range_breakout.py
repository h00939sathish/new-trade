from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
import numpy as np

from src.strategies.base import Strategy
from src.core.regime.ema200_filter import EMA200Filter, RegimeState

class OpeningRangeBreakoutStrategy(Strategy):
    """
    Opening Range Breakout (ORB) Strategy.
    - Opening Range: 09:15–09:30 IST
    - Long Entry: Break above OR high
    - Short Entry: Break below OR low
    - Filters: EMA200 Regime Filter, Volume > 1.2x average
    """
    def __init__(self, volume_multiplier: float = 1.2, atr_window: int = 14):
        self.name = "orb"
        self.data_type = "candle"
        self.timeframe = "minute"  # Works best on 1-minute or 5-minute candles
        self.volume_multiplier = volume_multiplier
        self.atr_window = atr_window
        self.ema_filter = EMA200Filter(period=200, slope_lookback=5)
        self._ist = ZoneInfo("Asia/Kolkata")

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[datetime] | None = None,
    ) -> dict[str, Any] | None:
        if not timestamps or len(prices) < 200:
            return None
        
        current_ts = timestamps[-1].astimezone(self._ist)
        
        # 1. Check time: only trade between 09:30 and 15:20 IST
        current_time = current_ts.time()
        if current_time < datetime.strptime("09:30", "%H:%M").time():
            return None
        if current_time > datetime.strptime("15:20", "%H:%M").time():
            return None

        # 2. Extract today's opening range (09:15 to 09:30)
        current_date = current_ts.date()
        or_high = -float('inf')
        or_low = float('inf')
        
        for i in range(len(timestamps)-1, -1, -1):
            ts_ist = timestamps[i].astimezone(self._ist)
            if ts_ist.date() != current_date:
                break
            
            t = ts_ist.time()
            if datetime.strptime("09:15", "%H:%M").time() <= t < datetime.strptime("09:30", "%H:%M").time():
                if highs and highs[i] > or_high:
                    or_high = highs[i]
                elif prices[i] > or_high:
                    or_high = prices[i]
                    
                if lows and lows[i] < or_low:
                    or_low = lows[i]
                elif prices[i] < or_low:
                    or_low = prices[i]

        if or_high == -float('inf') or or_low == float('inf'):
            return None

        # 3. Calculate EMA200 Regime
        regime = self.ema_filter.evaluate(prices)
        if regime == RegimeState.NO_TRADE:
            return None

        # 4. Calculate Volume Filter
        if volumes and len(volumes) >= 20:
            avg_volume = sum(volumes[-20:]) / 20
            current_volume = volumes[-1]
            if current_volume < avg_volume * self.volume_multiplier:
                return None
        
        # 5. Calculate ATR for SL/TP
        atr = 0.0
        if highs and lows and len(highs) >= self.atr_window:
            trs = []
            for j in range(len(prices) - self.atr_window, len(prices)):
                tr = max(
                    highs[j] - lows[j],
                    abs(highs[j] - prices[j-1]),
                    abs(lows[j] - prices[j-1])
                )
                trs.append(tr)
            atr = sum(trs) / len(trs)

        current_price = prices[-1]
        
        # 6. Check for Breakout
        direction = None
        if current_price > or_high and regime in (RegimeState.TREND_LONG_ALLOWED, RegimeState.MEAN_REVERSION_ONLY):
            direction = "long"
        elif current_price < or_low and regime in (RegimeState.TREND_SHORT_ALLOWED, RegimeState.MEAN_REVERSION_ONLY):
            direction = "short"

        if not direction:
            return None

        # Risk: Stop = 1 ATR, Target = 2 ATR
        sl_pct = (1.0 * atr) / current_price if atr > 0 else 0.01
        tp_pct = (2.0 * atr) / current_price if atr > 0 else 0.02

        range_size = or_high - or_low
        if range_size > 0:
            breakout_dist = (current_price - or_high) if direction == "long" else (or_low - current_price)
            confidence = min(0.5 + 0.5 * (breakout_dist / range_size), 0.95)
        else:
            confidence = 0.6

        return {
            "direction": direction,
            "confidence": confidence,
            "price": current_price,
            "features": {
                "or_high": or_high,
                "or_low": or_low,
                "atr": atr,
                "sl_pct_override": sl_pct,
                "tp_pct_override": tp_pct,
            },
        }
