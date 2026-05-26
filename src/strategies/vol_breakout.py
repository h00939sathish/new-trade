from typing import Any

from src.strategies.base import Strategy


class VolatilityBreakoutStrategy(Strategy):
    """
    Volatility Breakout Strategy (Donchian Channel/Turtle logic).
    Goes long if price breaks highest high of N periods.
    Goes short if price breaks lowest low of N periods.
    """
    def __init__(
        self,
        window: int = 20,
    ):
        self.name = "vol_breakout"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.window = window

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if not highs or not lows:
            # We need candle high/low data for true breakout
            return None

        if len(highs) < self.window + 1 or len(lows) < self.window + 1:
            return None

        # The previous N periods (excluding current incomplete period)
        prev_highs = highs[-(self.window + 1):-1]
        prev_lows = lows[-(self.window + 1):-1]

        highest_high = max(prev_highs)
        lowest_low = min(prev_lows)

        current_price = prices[-1]

        direction = None
        confidence = 0.8  # Breakout signals usually have a fixed high confidence in trend models

        if current_price > highest_high:
            direction = "long"
        elif current_price < lowest_low:
            direction = "short"

        if not direction:
            return None

        return {
            "direction": direction,
            "confidence": confidence,
            "price": current_price,
            "features": {
                "highest_high": highest_high,
                "lowest_low": lowest_low,
                "breakout_distance": current_price - highest_high if direction == "long" else lowest_low - current_price
            },
        }
