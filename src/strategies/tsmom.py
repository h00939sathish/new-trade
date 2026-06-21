import math
from typing import Any

import numpy as np

from src.strategies.base import Strategy


class TSMOMStrategy(Strategy):
    """
    Volatility-Scaled Time Series Momentum (TSMOM).
    - Signal Horizons: configurable (defaults to minute-bar equivalents).
    - Position Size = Trend Signal * (Target Volatility / Current Volatility)
    - Target Portfolio Volatility: 10% annualized.
    - bars_per_day: number of bars per trading day for timeframe scaling.
      Default 375 for 1-min bars on NSE (6.25h * 60min).
    """

    def __init__(
        self,
        target_volatility: float = 0.10,
        horizons: tuple = (60, 120, 250),
        bars_per_day: int = 375,
    ):
        self.name = "tsmom"
        self.data_type = "candle"
        self.timeframe = "1m"  # Default now matches the bars the system sends
        self.target_volatility = target_volatility
        self.horizons = horizons
        self.bars_per_day = bars_per_day
        # Vol lookback: ~60 trading days worth of bars
        self._vol_lookback = 60 * bars_per_day if bars_per_day else 60

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

        # Calculate annualized volatility using a configurable lookback window
        vol_window = min(self._vol_lookback, len(prices) - 1)
        ret = []
        for i in range(1, vol_window):
            if prices[-(i + 1)] > 0:
                ret.append((prices[-i] - prices[-(i + 1)]) / prices[-(i + 1)])
            else:
                ret.append(0.0)

        if not ret:
            return None

        bar_vol = np.std(ret)
        # Annualize based on bars_per_day
        ann_vol = bar_vol * math.sqrt(self.bars_per_day * 252) if self.bars_per_day else 0.0

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
