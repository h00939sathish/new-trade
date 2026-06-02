from typing import Any
import numpy as np

from src.strategies.base import Strategy

class VolatilityCompressionStrategy(Strategy):
    """
    Volatility Compression Breakout Strategy.
    - Bollinger Band Width < 20th percentile
    - ATR contracting (Current ATR < ATR MA)
    - Breakout from BB Upper/Lower band
    - Risk: 1 ATR stop loss
    """
    def __init__(
        self, 
        bb_window: int = 20, 
        bb_std: float = 2.0, 
        lookback: int = 100, 
        percentile_threshold: float = 20.0,
        atr_window: int = 14
    ):
        self.name = "vol_compression"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.lookback = lookback
        self.percentile_threshold = percentile_threshold
        self.atr_window = atr_window

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.lookback + self.bb_window or not highs or not lows:
            return None
        
        # Calculate Bollinger Bands over the lookback window to find Width history
        bb_widths = []
        for i in range(len(prices) - self.lookback, len(prices) + 1):
            window_prices = prices[i - self.bb_window : i]
            mean = np.mean(window_prices)
            std = np.std(window_prices)
            if mean > 0:
                upper = mean + self.bb_std * std
                lower = mean - self.bb_std * std
                width = (upper - lower) / mean
                bb_widths.append(width)
            else:
                bb_widths.append(0.0)

        # We want to check compression BEFORE the breakout candle
        # So we use index -2 for width and ATR checks
        current_width = bb_widths[-2]
        history_widths = bb_widths[:-2]
        
        if not history_widths:
            return None
            
        percentile = sum(1 for w in history_widths if w < current_width) / len(history_widths) * 100.0
        
        # Check if BB Width is below percentile threshold
        if percentile > self.percentile_threshold:
            return None
            
        # Calculate ATR and ATR MA
        trs = []
        for j in range(len(prices) - self.atr_window * 2, len(prices)):
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - prices[j-1]),
                abs(lows[j] - prices[j-1])
            )
            trs.append(tr)
            
        if len(trs) < self.atr_window * 2:
            return None
            
        atr_history = []
        for i in range(self.atr_window, len(trs) + 1):
            atr_history.append(np.mean(trs[i - self.atr_window : i]))
            
        # Check ATR on the previous candle (-2)
        prev_atr = atr_history[-2]
        atr_ma = np.mean(atr_history[:-2])
        
        # Check if ATR is contracting
        if prev_atr >= atr_ma:
            return None
            
        # Check for breakout from BB on the CURRENT candle (-1)
        current_price = prices[-1]
        
        # We need the BB upper/lower from the previous candle to see if we broke out of the compression zone
        prev_recent_prices = prices[-self.bb_window-1:-1]
        mean = np.mean(prev_recent_prices)
        std = np.std(prev_recent_prices)
        upper = mean + self.bb_std * std
        lower = mean - self.bb_std * std
        
        direction = None
        if current_price > upper:
            direction = "long"
        elif current_price < lower:
            direction = "short"
            
        if not direction:
            return None
            
        # SL is based on current ATR (which includes the breakout candle for better safety)
        current_atr = atr_history[-1]
        sl_pct = (1.0 * current_atr) / current_price if current_atr > 0 else 0.01
        
        # For trailing stop, we let the StrategyGenAgent dynamic trailing SL handle it
        # but we configure the initial stop loss pct to 1 ATR
        
        return {
            "direction": direction,
            "confidence": 0.8,
            "price": current_price,
            "features": {
                "bb_width_percentile": percentile,
                "current_atr": current_atr,
                "atr_ma": atr_ma,
                "sl_pct_override": sl_pct,
                # We do not override TP, letting the default TP take place or open trailing
            },
        }
