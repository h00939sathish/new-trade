import math
from typing import Any, Literal

from src.strategies.base import Strategy


class MomentumStrategy(Strategy):
    def __init__(self, short_window: int = 5, long_window: int = 20, threshold: float = 0.02):
        self.name = "momentum"
        self.data_type = "any"
        self.timeframe = "minute"
        self.short_window = short_window
        self.long_window = long_window
        self.threshold = threshold

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.long_window:
            return None
        short_ma = sum(prices[-self.short_window:]) / self.short_window
        long_ma = sum(prices[-self.long_window:]) / self.long_window
        ratio = (short_ma - long_ma) / long_ma
        if abs(ratio) < self.threshold:
            return None
        direction: Literal["long", "short"] = "long" if ratio > 0 else "short"
        confidence = min(abs(ratio) / 0.05, 0.95)
        return {
            "direction": direction,
            "confidence": confidence,
            "price": prices[-1],
            "features": {
                "short_ma": short_ma,
                "long_ma": long_ma,
                "ratio": ratio,
            },
        }


class MeanReversionStrategy(Strategy):
    def __init__(self, window: int = 20, entry_z: float = 2.0, exit_z: float = 0.5):
        self.name = "mean_reversion"
        self.data_type = "any"
        self.timeframe = "minute"
        self.window = window
        self.entry_z = entry_z
        self.exit_z = exit_z

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.window:
            return None
        recent = prices[-self.window:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std = math.sqrt(variance) if variance > 0 else 1.0
        current_price = prices[-1]
        z_score = (current_price - mean) / std
        if abs(z_score) < self.entry_z:
            return None
        direction: Literal["long", "short"] = "long" if z_score < 0 else "short"
        confidence = min(abs(z_score) / (self.entry_z * 2), 0.95)
        return {
            "direction": direction,
            "confidence": confidence,
            "price": current_price,
            "features": {
                "mean": mean,
                "std": std,
                "z_score": z_score,
            },
        }


class ATRStrategy(Strategy):
    def __init__(self, window: int = 14, multiplier: float = 2.0, threshold: float = 0.01):
        self.name = "atr_breakout"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.window = window
        self.multiplier = multiplier
        self.threshold = threshold

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.window + 1:
            return None

        # Use real high/low if available, otherwise approximate from close prices
        if highs and lows and len(highs) >= self.window + 1 and len(lows) >= self.window + 1:
            recent_highs = highs[-(self.window + 1):]
            recent_lows = lows[-(self.window + 1):]
            recent_closes = prices[-(self.window + 1):]
            tr_values = []
            for i in range(1, len(recent_closes)):
                # Proper True Range: max(H-L, |H-C_prev|, |L-C_prev|)
                tr = max(
                    recent_highs[i] - recent_lows[i],
                    abs(recent_highs[i] - recent_closes[i - 1]),
                    abs(recent_lows[i] - recent_closes[i - 1]),
                )
                tr_values.append(tr)
        else:
            # Fallback: approximate from close-only
            recent = prices[-(self.window + 1):]
            tr_values = []
            for i in range(1, len(recent)):
                high = max(recent[i], recent[i-1])
                low = min(recent[i], recent[i-1])
                tr_values.append(high - low)
        atr = sum(tr_values) / len(tr_values)
        current = prices[-1]
        prev = prices[-2]
        if prev == 0:
            return None
        change = (current - prev) / prev
        if abs(change) < self.threshold:
            return None
        ratio = abs(change) / atr if atr > 0 else 0
        direction = "long" if change > 0 else "short"
        confidence = min(ratio / self.multiplier, 0.95)
        return {
            "direction": direction,
            "confidence": confidence,
            "price": current,
            "features": {
                "atr": atr,
                "change_pct": change,
                "ratio": ratio,
            },
        }


class BollingerBandsStrategy(Strategy):
    def __init__(self, window: int = 20, num_std: float = 2.0):
        self.name = "bollinger"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.window = window
        self.num_std = num_std

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.window:
            return None
        recent = prices[-self.window:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std = math.sqrt(variance) if variance > 0 else 1.0
        upper = mean + self.num_std * std
        lower = mean - self.num_std * std
        current = prices[-1]
        if lower < current < upper:
            return None
        direction = "long" if current <= lower else "short"
        distance = min(abs(current - mean) / (self.num_std * std), 1.0) if std > 0 else 0
        confidence = min(distance, 0.95)
        return {
            "direction": direction,
            "confidence": confidence,
            "price": current,
            "features": {
                "mean": mean,
                "std": std,
                "upper": upper,
                "lower": lower,
                "band_width": (upper - lower) / mean if mean > 0 else 0,
            },
        }


class RSIStrategy(Strategy):
    def __init__(self, window: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        self.name = "rsi"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.window = window
        self.oversold = oversold
        self.overbought = overbought

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.window + 1:
            return None
        gains, losses = [], []
        for i in range(-self.window, 0):
            change = prices[i] - prices[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / self.window
        avg_loss = sum(losses) / self.window
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        current = prices[-1]
        if self.oversold < rsi < self.overbought:
            return None
        direction = "long" if rsi <= self.oversold else "short"
        distance = abs(rsi - 50.0) / 50.0
        confidence = min(distance, 0.95)
        return {
            "direction": direction,
            "confidence": confidence,
            "price": current,
            "features": {
                "rsi": rsi,
                "avg_gain": avg_gain,
                "avg_loss": avg_loss,
            },
        }


class MACDStrategy(Strategy):
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, threshold: float = 0.0):
        self.name = "macd"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.threshold = threshold

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.slow + self.signal + 1:
            return None
        ema_fast = self._ema(prices, self.fast)
        ema_slow = self._ema(prices, self.slow)
        offset = self.slow - self.fast
        macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]
        signal_line = self._ema(macd_line, self.signal)
        if len(macd_line) < 2 or len(signal_line) < 2:
            return None
        curr = macd_line[-1]
        prev = macd_line[-2]
        curr_sig = signal_line[-1]
        prev_sig = signal_line[-2]
        hist = curr - curr_sig
        if abs(hist) <= self.threshold:
            return None
        direction = "long" if hist > 0 else "short"
        confidence = min(abs(hist) / (abs(curr_sig) + 1e-10), 0.95)
        prev_hist = prev - prev_sig
        cross = "none"
        if prev_hist <= 0 < hist:
            cross = "bullish"
        elif prev_hist >= 0 > hist:
            cross = "bearish"
        return {
            "direction": direction,
            "confidence": confidence,
            "price": prices[-1],
            "features": {
                "macd": curr,
                "signal": curr_sig,
                "histogram": hist,
                "cross": cross,
            },
        }

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if len(values) < period:
            return []
        k = 2.0 / (period + 1)
        result = [sum(values[:period]) / period]
        for v in values[period:]:
            result.append((v - result[-1]) * k + result[-1])
        return result


class VolumeStrategy(Strategy):
    def __init__(self, volume_window: int = 20, price_window: int = 10, volume_mult: float = 1.5):
        self.name = "volume"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.volume_window = volume_window
        self.price_window = price_window
        self.volume_mult = volume_mult

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if volumes is None:
            return None
        return await self.evaluate_with_volume(instrument, prices, volumes)

    async def evaluate_with_volume(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float],
    ) -> dict[str, Any] | None:
        if len(prices) < self.price_window or len(volumes) < self.volume_window:
            return None
        recent_vol = volumes[-self.volume_window:]
        avg_vol = sum(recent_vol) / len(recent_vol)
        curr_vol = volumes[-1]
        if curr_vol <= avg_vol * self.volume_mult:
            return None
        price_change = (prices[-1] - prices[-self.price_window]) / prices[-self.price_window]
        if abs(price_change) < 0.005:
            return None
        direction = "long" if price_change > 0 else "short"
        confidence = min(curr_vol / (avg_vol * 3) if avg_vol > 0 else 0, 0.95)
        return {
            "direction": direction,
            "confidence": confidence,
            "price": prices[-1],
            "features": {
                "volume_ratio": curr_vol / avg_vol if avg_vol > 0 else 0,
                "avg_volume": avg_vol,
                "current_volume": curr_vol,
                "price_change_pct": price_change,
            },
        }


class IchimokuStrategy(Strategy):
    def __init__(self, conversion: int = 9, base: int = 26, lagging: int = 52, displacement: int = 26):
        self.name = "ichimoku"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.conversion = conversion
        self.base = base
        self.lagging = lagging
        self.displacement = displacement

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if len(prices) < self.lagging + self.displacement:
            return None
        conv = self._midpoint(prices, self.conversion)
        base = self._midpoint(prices, self.base)
        if conv is None or base is None:
            return None
        current = prices[-1]
        if conv > base and current > conv:
            direction = "long"
            confidence = min(abs(conv - base) / (base + 1e-10) * 10, 0.95)
        elif conv < base and current < base:
            direction = "short"
            confidence = min(abs(conv - base) / (base + 1e-10) * 10, 0.95)
        else:
            return None
        return {
            "direction": direction,
            "confidence": confidence,
            "price": current,
            "features": {
                "conversion": conv,
                "base": base,
                "cloud_top": max(conv, base),
                "cloud_bottom": min(conv, base),
            },
        }

    @staticmethod
    def _midpoint(prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None
        segment = prices[-period:]
        return (max(segment) + min(segment)) / 2
