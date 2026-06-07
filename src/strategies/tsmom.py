import math
from typing import Any

import numpy as np

from src.strategies.base import Strategy


class TSMOMStrategy(Strategy):
    """
    Volatility-Scaled Time Series Momentum (TSMOM).
    - Signal Horizons: 60-day, 120-day, 250-day.
    - Position Size = Trend Signal * (Target Volatility / Current Volatility)
    - Target Portfolio Volatility: 10% annualized.
    """

    def __init__(self, target_volatility: float = 0.10, horizons: tuple = (60, 120, 250)):
        self.name = "tsmom"
        self.data_type = "candle"
        self.timeframe = "1d"  # Operates on daily data
        self.target_volatility = target_volatility
        self.horizons = horizons

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        max_horizon = max(self.horizons)
        if len(prices) < max_horizon + 2:
            return None

        current_price = prices[-1]

        # Calculate annualized volatility of daily returns over the last 60 days
        ret = []
        for i in range(len(prices) - 60, len(prices)):
            if prices[i - 1] > 0:
                ret.append((prices[i] - prices[i - 1]) / prices[i - 1])
            else:
                ret.append(0.0)

        if not ret:
            return None

        daily_vol = np.std(ret)
        ann_vol = daily_vol * math.sqrt(252)

        if ann_vol <= 0:
            return None

        # Volatility scalar
        vol_scalar = self.target_volatility / ann_vol

        # Calculate average momentum signal across horizons
        signals = []
        for h in self.horizons:
            past_price = prices[-h - 1]
            if past_price > 0:
                sign = 1 if current_price > past_price else -1 if current_price < past_price else 0
                signals.append(sign)

        avg_signal = np.mean(signals)

        if avg_signal == 0:
            return None

        direction = "long" if avg_signal > 0 else "short"
        confidence = abs(avg_signal)

        # Position multiplier based on volatility scaling
        position_multiplier = confidence * vol_scalar

        return {
            "direction": direction,
            "confidence": confidence,
            "price": current_price,
            "features": {
                "ann_vol": ann_vol,
                "vol_scalar": vol_scalar,
                "avg_signal": avg_signal,
                "position_multiplier": position_multiplier,
            },
        }
