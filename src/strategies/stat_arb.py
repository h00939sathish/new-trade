from typing import Any

import numpy as np

from src.strategies.base import Strategy


class StatArbStrategy(Strategy):
    """
    Statistical Arbitrage (Pairs Trading) Strategy using Z-Score of the spread.
    This strategy is designed to work with two highly correlated assets.
    """
    def __init__(
        self,
        primary_symbol: str = "TCS",
        secondary_symbol: str = "INFY",
        window: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
    ):
        self.name = "stat_arb"
        self.data_type = "any"
        self.timeframe = "minute"
        self.primary_symbol = primary_symbol
        self.secondary_symbol = secondary_symbol
        self.window = window
        self.entry_z = entry_z
        self.exit_z = exit_z
        self._primary_prices: list[float] = []
        self._secondary_prices: list[float] = []

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        # We need both prices to compute the spread.
        # This strategy tracks prices internally for both symbols.
        if instrument == self.primary_symbol:
            self._primary_prices = prices[-self.window:]
        elif instrument == self.secondary_symbol:
            self._secondary_prices = prices[-self.window:]

        if len(self._primary_prices) < self.window or len(self._secondary_prices) < self.window:
            return None

        # Calculate Spread: Primary - Secondary (assuming 1:1 ratio for simplicity)
        primary_arr = np.array(self._primary_prices[-self.window:])
        secondary_arr = np.array(self._secondary_prices[-self.window:])
        spread = primary_arr - secondary_arr

        mean = np.mean(spread)
        std = np.std(spread)
        if std == 0:
            return None

        current_spread = spread[-1]
        z_score = (current_spread - mean) / std

        direction = None
        confidence = min(abs(z_score) / (self.entry_z * 2), 0.95)

        # Mean Reversion Logic
        if z_score > self.entry_z:
            # Spread is too high -> Primary is overvalued relative to Secondary
            # We short Primary and long Secondary. (We only emit signal for the instrument evaluated)
            if instrument == self.primary_symbol:
                direction = "short"
            elif instrument == self.secondary_symbol:
                direction = "long"
        elif z_score < -self.entry_z:
            # Spread is too low -> Primary is undervalued relative to Secondary
            # We long Primary and short Secondary
            if instrument == self.primary_symbol:
                direction = "long"
            elif instrument == self.secondary_symbol:
                direction = "short"

        if not direction:
            return None

        return {
            "direction": direction,
            "confidence": confidence,
            "price": prices[-1],
            "features": {
                "z_score": float(z_score),
                "spread_mean": float(mean),
                "spread_std": float(std),
                "current_spread": float(current_spread),
                "primary_price": self._primary_prices[-1],
                "secondary_price": self._secondary_prices[-1],
            },
        }
