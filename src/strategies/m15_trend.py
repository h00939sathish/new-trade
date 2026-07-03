import math
from datetime import UTC, datetime
from typing import Any


def _round_to_m15(dt: datetime) -> datetime:
    minute = dt.minute // 15 * 15
    return dt.replace(minute=minute, second=0, microsecond=0)


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * k + ema
    return ema


def _adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    if len(closes) < period + 1:
        return None
    tr_sum = 0.0
    dm_plus_sum = 0.0
    dm_minus_sum = 0.0
    for i in range(1, period + 1):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_sum += tr
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        dm_plus_sum += up_move if up_move > down_move and up_move > 0 else 0
        dm_minus_sum += down_move if down_move > up_move and down_move > 0 else 0
    if tr_sum == 0:
        return None
    di_plus = 100 * dm_plus_sum / tr_sum
    di_minus = 100 * dm_minus_sum / tr_sum
    dx = (
        100 * abs(di_plus - di_minus) / (di_plus + di_minus)
        if (di_plus + di_minus) > 0
        else 0
    )
    return dx


class M15TrendConfirmation:
    def __init__(self, ema_period: int = 20, adx_period: int = 14):
        self._ema_period = ema_period
        self._adx_period = adx_period
        self._m15_bars: list[dict[str, Any]] = []

    def update(self, candle: dict[str, Any]) -> None:
        ts = candle["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        bucket_key = _round_to_m15(ts)

        if (
            self._m15_bars
            and self._m15_bars[-1]["timestamp"] == bucket_key
        ):
            bar = self._m15_bars[-1]
            bar["high"] = max(bar["high"], candle["high"])
            bar["low"] = min(bar["low"], candle["low"])
            bar["close"] = candle["close"]
            bar["volume"] = bar.get("volume", 0) + candle.get("volume", 0)
        else:
            new_bar = {
                "timestamp": bucket_key,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle.get("volume", 0),
            }
            self._m15_bars.append(new_bar)

    def is_warmed(self) -> bool:
        return len(self._m15_bars) >= self._ema_period

    def get_regime(self) -> str | None:
        if not self.is_warmed():
            return None
        closes = [b["close"] for b in self._m15_bars]
        highs = [b["high"] for b in self._m15_bars]
        lows = [b["low"] for b in self._m15_bars]
        ema = _ema(closes, self._ema_period)
        adx_val = _adx(highs, lows, closes, self._adx_period)
        if ema is None or adx_val is None:
            return None
        current_close = closes[-1]
        if current_close > ema and adx_val > 25:
            return "trending_up"
        elif current_close < ema and adx_val > 25:
            return "trending_down"
        else:
            return "ranging"

    def confirms(self, direction: str) -> bool:
        regime = self.get_regime()
        if regime is None:
            return False
        if direction == "buy":
            return regime == "trending_up"
        elif direction == "sell":
            return regime == "trending_down"
        return False
