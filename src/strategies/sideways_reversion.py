from typing import Any
import numpy as np

from src.strategies.base import Strategy
from src.core.regime.ema200_filter import EMA200Filter, RegimeState

class SidewaysReversionStrategy(Strategy):
    """
    Sideways Mean Reversion Strategy.
    - Only active when Regime == SIDEWAYS / MEAN_REVERSION_ONLY
    - Entry: RSI < 30 and Price < Lower Bollinger Band -> Long
    - Exit: RSI > 50 and Price returns to BB midline -> Exit (handled by StrategyGenAgent tracking if we emit exit or we just emit entry and rely on TP/SL)
      Wait, we will emit short signal or neutral signal? Actually, we just emit entry, and we can set the Take Profit dynamically to the BB Midline.
    """
    def __init__(self, rsi_window: int = 14, bb_window: int = 20, bb_std: float = 2.0, atr_window: int = 14):
        self.name = "sideways_reversion"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.rsi_window = rsi_window
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.atr_window = atr_window
        self.ema_filter = EMA200Filter(period=200, slope_lookback=5)

    def _calculate_rsi(self, prices: list[float]) -> float:
        if len(prices) < self.rsi_window + 1:
            return 50.0
            
        gains = []
        losses = []
        for i in range(len(prices) - self.rsi_window, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
                
        avg_gain = sum(gains) / self.rsi_window
        avg_loss = sum(losses) / self.rsi_window
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < max(self.bb_window, self.rsi_window, self.ema_filter.period + self.ema_filter.slope_lookback, self.atr_window):
            return None
            
        # Check regime
        regime = self.ema_filter.evaluate(prices)
        if regime != RegimeState.MEAN_REVERSION_ONLY:
            return None
            
        # Calculate RSI
        rsi = self._calculate_rsi(prices)
        
        # Calculate Bollinger Bands
        recent_prices = prices[-self.bb_window:]
        mean = np.mean(recent_prices)
        std = np.std(recent_prices)
        upper = mean + self.bb_std * std
        lower = mean - self.bb_std * std
        
        current_price = prices[-1]
        
        direction = None
        if rsi < 30 and current_price < lower:
            direction = "long"
        elif rsi > 70 and current_price > upper:
            direction = "short"
            
        if not direction:
            return None
            
        # Calculate ATR for stop loss
        trs = []
        for j in range(len(prices) - self.atr_window, len(prices)):
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - prices[j-1]),
                abs(lows[j] - prices[j-1])
            )
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else 0.0
        
        sl_pct = (1.0 * atr) / current_price if atr > 0 else 0.01
        # Target TP is the BB mean
        tp_pct = abs(mean - current_price) / current_price if mean != current_price else 0.02
        
        return {
            "direction": direction,
            "confidence": 0.8,
            "price": current_price,
            "features": {
                "rsi": rsi,
                "bb_lower": lower,
                "bb_upper": upper,
                "bb_mean": mean,
                "atr": atr,
                "sl_pct_override": sl_pct,
                "tp_pct_override": tp_pct,
            },
        }
