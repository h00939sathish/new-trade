from enum import StrEnum


class RegimeState(StrEnum):
    TREND_LONG_ALLOWED = "TREND_LONG_ALLOWED"
    TREND_SHORT_ALLOWED = "TREND_SHORT_ALLOWED"
    MEAN_REVERSION_ONLY = "MEAN_REVERSION_ONLY"
    NO_TRADE = "NO_TRADE"


class EMA200Filter:
    def __init__(self, period: int = 200, slope_lookback: int = 5):
        self.period = period
        self.slope_lookback = slope_lookback

    def evaluate(self, closes: list[float]) -> RegimeState:
        if len(closes) < self.period + self.slope_lookback:
            return RegimeState.NO_TRADE

        multiplier = 2.0 / (self.period + 1)
        sma = sum(closes[: self.period]) / self.period
        ema = [sma]
        for i in range(self.period, len(closes)):
            ema.append((closes[i] - ema[-1]) * multiplier + ema[-1])

        current_ema = ema[-1]
        past_ema = ema[-self.slope_lookback]
        current_close = closes[-1]
        slope = current_ema - past_ema

        if current_close > current_ema and slope > 0:
            return RegimeState.TREND_LONG_ALLOWED
        elif current_close < current_ema and slope < 0:
            return RegimeState.TREND_SHORT_ALLOWED
        else:
            return RegimeState.MEAN_REVERSION_ONLY
