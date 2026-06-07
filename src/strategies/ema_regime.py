import math
from src.strategies.base import Strategy


class Ema200RegimeGate(Strategy):
    def __init__(self, lookback: int = 200):
        self.name = "ema200_regime_gate"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.lookback = max(lookback, 20)

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list | None = None,
    ) -> dict[str, object] | None:
        if len(prices) < self.lookback:
            return None

        closes = [float(p) for p in prices[-self.lookback:]]
        ema = closes[0]
        multiplier = 2.0 / (self.lookback + 1)
        for c in closes[1:]:
            ema = (c - ema) * multiplier + ema

        price = closes[-1]
        if math.isnan(ema) or ema <= 0:
            return None

        if price > ema * 1.001:
            direction = "long"
            confidence = min((price / ema) - 1.0, 0.95)
        elif price < ema * 0.999:
            direction = "short"
            confidence = min(1.0 - (price / ema), 0.95)
        else:
            direction = "neutral"
            confidence = 0.0

        return {
            "direction": direction,
            "confidence": confidence,
            "price": price,
            "features": {
                "ema": ema,
                "price_vs_ema": price / ema,
                "lookback": self.lookback,
            },
        }
