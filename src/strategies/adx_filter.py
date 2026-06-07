"""
ADX Regime Filter — non-voting regime detection for strategy_gen.

Classifies the current market micro-regime using Wilder's Average Directional
Index (ADX) so that downstream voting strategies can adapt position sizing,
entry filters, or be skipped entirely in unfavourable regimes.

Regime map
----------
ADX > 25  and +DI > −DI  →  trending_up
ADX > 25  and −DI > +DI  →  trending_down
ADX < 20                 →  range_bound
20 ≤ ADX ≤ 25            →  transitional

Weight is 0.0 — the strategy never votes on direction but still emits a
signal dict so the ensemble layer can inspect ``features["regime"]``.
"""

import numpy as np

from src.strategies.base import Strategy


class AdxRegimeFilter(Strategy):
    """Non-voting ADX regime gate for NSE Nifty-50 intraday strategies."""

    def __init__(self, period: int = 14):
        self.name = "adx_regime_filter"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.period = period
        # 2× period: first `period` bars for initial smoothing, next `period`
        # bars to produce the first valid ADX via Wilder's smoothed average.
        self.min_bars = 2 * period + 1  # 29 for period=14

    # ------------------------------------------------------------------
    # Wilder helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _wilders_smooth(values: np.ndarray, period: int) -> np.ndarray:
        """Wilder's smoothing (exponential with alpha = 1/period).

        First value is the simple sum of the first *period* elements;
        subsequent values use the recurrence:
            smoothed[i] = smoothed[i-1] - smoothed[i-1]/period + values[i]
        """
        n = len(values)
        out = np.empty(n, dtype=np.float64)
        out[:period] = np.nan

        # Seed with the simple sum (not average — Wilder uses the sum for
        # +DM / −DM / TR, then divides later when computing +DI / −DI).
        out[period] = np.sum(values[: period + 1])

        for i in range(period + 1, n):
            out[i] = out[i - 1] - (out[i - 1] / period) + values[i]

        return out

    @staticmethod
    def _wilders_average(values: np.ndarray, period: int) -> np.ndarray:
        """Wilder's smoothed *average* (used for ADX from DX series).

        Seed is the simple mean of the first *period* valid values; then:
            avg[i] = (avg[i-1] * (period - 1) + values[i]) / period
        """
        n = len(values)
        out = np.empty(n, dtype=np.float64)

        # Find the first `period` non-NaN values in `values` to seed.
        valid_mask = ~np.isnan(values)
        valid_idx = np.flatnonzero(valid_mask)

        if len(valid_idx) < period:
            out[:] = np.nan
            return out

        seed_end = valid_idx[period - 1]  # index of period-th valid value
        out[:seed_end] = np.nan
        out[seed_end] = np.nanmean(values[valid_idx[0] : seed_end + 1])

        for i in range(seed_end + 1, n):
            if np.isnan(values[i]):
                out[i] = out[i - 1]
            else:
                out[i] = (out[i - 1] * (period - 1) + values[i]) / period

        return out

    # ------------------------------------------------------------------
    # Core ADX calculation
    # ------------------------------------------------------------------
    def _compute_adx(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> tuple[float, float, float]:
        """Return (adx, plus_di, minus_di) for the most recent bar.

        All arrays must be the same length (>= self.min_bars).
        """
        # --- Directional Movement & True Range (bar-by-bar) -----------
        len(closes)

        up_move = np.diff(highs)  # high[i] - high[i-1]
        down_move = np.diff(-lows)  # low[i-1] - low[i]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # True Range
        h_l = highs[1:] - lows[1:]
        h_pc = np.abs(highs[1:] - closes[:-1])
        l_pc = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(h_l, np.maximum(h_pc, l_pc))

        # --- Wilder's smoothing of +DM, −DM, TR ----------------------
        period = self.period
        sm_plus_dm = self._wilders_smooth(plus_dm, period)
        sm_minus_dm = self._wilders_smooth(minus_dm, period)
        sm_tr = self._wilders_smooth(tr, period)

        # --- +DI / −DI -----------------------------------------------
        # Avoid division by zero: if smoothed TR is 0, DI is 0.
        with np.errstate(divide="ignore", invalid="ignore"):
            plus_di = np.where(sm_tr != 0, 100.0 * sm_plus_dm / sm_tr, 0.0)
            minus_di = np.where(sm_tr != 0, 100.0 * sm_minus_dm / sm_tr, 0.0)

        # --- DX -------------------------------------------------------
        di_sum = plus_di + minus_di
        with np.errstate(divide="ignore", invalid="ignore"):
            dx = np.where(di_sum != 0, 100.0 * np.abs(plus_di - minus_di) / di_sum, 0.0)
        dx = np.where(np.isnan(plus_di) | np.isnan(minus_di), np.nan, dx)

        # --- ADX (Wilder's smoothed average of DX) --------------------
        adx_arr = self._wilders_average(dx, period)

        # Return latest values
        adx_val = float(adx_arr[-1])
        pdi_val = float(plus_di[-1])
        mdi_val = float(minus_di[-1])
        return adx_val, pdi_val, mdi_val

    # ------------------------------------------------------------------
    # Strategy interface
    # ------------------------------------------------------------------
    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list | None = None,
    ) -> dict[str, object] | None:
        # ADX requires OHLC — bail out if highs/lows are missing.
        if highs is None or lows is None:
            return None

        if len(prices) < self.min_bars or len(highs) < self.min_bars or len(lows) < self.min_bars:
            return None

        closes = np.asarray(prices, dtype=np.float64)
        h = np.asarray(highs, dtype=np.float64)
        l = np.asarray(lows, dtype=np.float64)

        adx, plus_di, minus_di = self._compute_adx(h, l, closes)

        # Guard against NaN from insufficient history.
        if np.isnan(adx) or np.isnan(plus_di) or np.isnan(minus_di):
            return None

        # --- Regime classification ------------------------------------
        if adx > 25.0:
            if plus_di > minus_di:
                direction = "long"
                regime = "trending_up"
            else:
                direction = "short"
                regime = "trending_down"
        elif adx < 20.0:
            direction = "neutral"
            regime = "range_bound"
        else:
            # 20 <= adx <= 25
            direction = "neutral"
            regime = "transitional"

        # --- Dynamic confidence from ADX strength --------------------
        # Map ADX 0‑50+ to confidence 0.0‑0.95.  Higher ADX = more
        # conviction that the detected regime is real.
        confidence = float(np.clip(adx / 50.0, 0.0, 0.95))

        # Neutral regimes get zero confidence (no directional conviction).
        if direction == "neutral":
            confidence = 0.0

        return {
            "direction": direction,
            "confidence": confidence,
            "price": float(closes[-1]),
            "features": {
                "adx": round(adx, 4),
                "plus_di": round(plus_di, 4),
                "minus_di": round(minus_di, 4),
                "regime": regime,
            },
        }
