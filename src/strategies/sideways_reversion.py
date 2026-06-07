from src.strategies.base import Strategy


class SidewaysReversionStrategy(Strategy):
    def __init__(self, rsi_window: int = 14, bb_window: int = 20, bb_std: float = 2.0, atr_window: int = 14):
        self.name = "sideways_reversion"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.rsi_window = rsi_window
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.atr_window = atr_window

    def _calculate_rsi(self, prices: list[float]) -> float:
        if len(prices) < self.rsi_window + 1:
            return 50.0

        gains: list[float] = []
        losses: list[float] = []
        start = len(prices) - self.rsi_window
        for i in range(start, len(prices)):
            change = prices[i] - prices[i - 1]
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
        timestamps: list[object] | None = None,
    ) -> dict[str, object] | None:
        required = max(self.bb_window, self.rsi_window, self.atr_window)
        if not highs or not lows or len(highs) < required or len(lows) < required or len(prices) < required:
            return None

        rsi = self._calculate_rsi(prices)
        recent_prices = prices[-self.bb_window :]
        mean = sum(recent_prices) / len(recent_prices)
        if len(recent_prices) < 2:
            std = 0.0
        else:
            mean_of_squares = sum(p * p for p in recent_prices) / len(recent_prices)
            mean_squared = mean * mean
            variance = mean_of_squares - mean_squared
            std = variance ** 0.5 if variance > 0 else 0.0
        upper = mean + self.bb_std * std
        lower = mean - self.bb_std * std
        current_price = prices[-1]

        direction: str | None = None
        if rsi < 30 and current_price < lower:
            direction = "long"
        elif rsi > 70 and current_price > upper:
            direction = "short"

        if not direction:
            return None

        trs: list[float] = []
        start = len(prices) - self.atr_window
        for j in range(start, len(prices)):
            h = highs[j]
            l = lows[j]
            c_prev = prices[j - 1]
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else 0.0

        sl_pct = (1.0 * atr) / current_price if atr > 0 else 0.01
        tp_pct = abs(mean - current_price) / current_price if mean != current_price else 0.02

        return {
            "direction": direction,
            "confidence": min(0.5 + 0.4 * (abs(rsi - 50) / 50), 0.95),
            "price": current_price,
            "features": {
                "regime": "mean_reverting",
                "rsi": rsi,
                "bb_lower": lower,
                "bb_upper": upper,
                "bb_mean": mean,
                "atr": atr,
                "sl_pct_override": sl_pct,
                "tp_pct_override": tp_pct,
            },
        }
