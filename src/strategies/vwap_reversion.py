"""
VWAP Reversion Strategy
=======================
A VWAP-anchored mean reversion strategy designed for NSE Nifty 50 intraday
trading. Identifies oversold/overbought conditions when price deviates beyond
configurable standard deviation bands from the session VWAP, confirmed by
above-average volume participation.

Signal logic:
  LONG  — price < VWAP - band_mult * σ  AND  volume > vol_mult * avg_volume
  SHORT — price > VWAP + band_mult * σ  AND  volume > vol_mult * avg_volume

Risk management:
  Stop-loss  — 1 × ATR from entry
  Take-profit — distance back to VWAP
"""

from typing import Any

import numpy as np

from src.strategies.base import Strategy


class VwapReversionStrategy(Strategy):
    """
    Mean-reversion strategy anchored to the Volume-Weighted Average Price.

    Trades reversions when price stretches beyond VWAP standard deviation bands
    with confirming volume. Confidence scales dynamically with the magnitude of
    the deviation — larger dislocations produce higher conviction, capped at 0.95.

    Parameters
    ----------
    min_periods : int
        Minimum number of data points required before generating signals.
    band_mult : float
        Number of VWAP standard deviations to define the signal threshold.
    vol_mult : float
        Minimum volume ratio vs. average volume for signal confirmation.
    atr_window : int
        Lookback window for ATR calculation (used for stop-loss sizing).
    max_confidence : float
        Upper cap on dynamic confidence values.
    """

    def __init__(
        self,
        min_periods: int = 20,
        band_mult: float = 1.5,
        vol_mult: float = 1.2,
        atr_window: int = 14,
        max_confidence: float = 0.95,
    ):
        self.name = "vwap_reversion"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.min_periods = min_periods
        self.band_mult = band_mult
        self.vol_mult = vol_mult
        self.atr_window = atr_window
        self.max_confidence = max_confidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_vwap(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
    ) -> tuple[float, float]:
        """
        Compute cumulative VWAP and its standard deviation for the session.

        Returns
        -------
        vwap : float
            Volume-weighted average price.
        vwap_std : float
            Standard deviation of typical price around the VWAP, weighted by
            cumulative volume.
        """
        typical_prices = (highs + lows + closes) / 3.0
        cum_vol = np.cumsum(volumes)
        cum_tp_vol = np.cumsum(typical_prices * volumes)

        # Avoid division by zero
        if cum_vol[-1] == 0:
            return float(closes[-1]), 0.0

        vwap = cum_tp_vol[-1] / cum_vol[-1]

        # Volume-weighted standard deviation of typical price from VWAP
        squared_dev = (typical_prices - vwap) ** 2
        cum_sq_dev_vol = np.cumsum(squared_dev * volumes)
        variance = cum_sq_dev_vol[-1] / cum_vol[-1]
        vwap_std = float(np.sqrt(variance)) if variance > 0 else 0.0

        return float(vwap), vwap_std

    def _compute_atr(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> float:
        """Compute Average True Range over the configured window."""
        window = min(self.atr_window, len(closes) - 1)
        if window <= 0:
            return 0.0

        h = highs[-window:]
        l = lows[-window:]
        c_prev = closes[-(window + 1) : -1]

        tr = np.maximum(h - l, np.maximum(np.abs(h - c_prev), np.abs(l - c_prev)))
        return float(np.mean(tr))

    # ------------------------------------------------------------------
    # Main evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Evaluate the VWAP reversion signal for *instrument*.

        Returns a signal dict when a valid entry is detected, or ``None``
        when data is insufficient or no actionable setup exists.
        """
        # ---- Guard: require highs, lows, and volumes -----------------
        if highs is None or lows is None or volumes is None:
            return None

        n = len(prices)
        if n < self.min_periods or len(highs) < n or len(lows) < n or len(volumes) < n:
            return None

        # ---- Convert to numpy arrays ---------------------------------
        h = np.asarray(highs, dtype=np.float64)
        l = np.asarray(lows, dtype=np.float64)
        c = np.asarray(prices, dtype=np.float64)
        v = np.asarray(volumes, dtype=np.float64)

        # ---- VWAP and bands ------------------------------------------
        vwap, vwap_std = self._compute_vwap(h, l, c, v)

        if vwap_std == 0:
            return None  # No dispersion — no meaningful signal

        upper_band = vwap + self.band_mult * vwap_std
        lower_band = vwap - self.band_mult * vwap_std
        current_price = float(c[-1])

        # ---- Volume confirmation -------------------------------------
        avg_volume = float(np.mean(v))
        current_volume = float(v[-1])
        volume_confirmed = avg_volume > 0 and current_volume > self.vol_mult * avg_volume

        if not volume_confirmed:
            return None

        # ---- Direction -----------------------------------------------
        direction: str | None = None
        if current_price < lower_band:
            direction = "long"
        elif current_price > upper_band:
            direction = "short"

        if direction is None:
            return None

        # ---- Dynamic confidence --------------------------------------
        # Scale linearly with deviation from VWAP (in units of σ).
        # 1.5σ → base ~0.55, 3σ → ~0.80, 4σ+ → capped at max_confidence.
        deviation_sigma = abs(current_price - vwap) / vwap_std
        # Map [1.5 .. 4.0] → [0.55 .. max_confidence]
        confidence = 0.55 + (deviation_sigma - self.band_mult) * (
            (self.max_confidence - 0.55) / (4.0 - self.band_mult)
        )
        confidence = float(np.clip(confidence, 0.40, self.max_confidence))

        # ---- Risk parameters ----------------------------------------
        atr = self._compute_atr(h, l, c)
        sl_pct = (atr / current_price) if atr > 0 else 0.01
        tp_pct = abs(vwap - current_price) / current_price if current_price != 0 else 0.02

        # ---- Volume ratio for features ------------------------------
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0.0

        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "price": current_price,
            "features": {
                "regime": "mean_reverting",
                "vwap": round(vwap, 2),
                "vwap_std": round(vwap_std, 4),
                "upper_band": round(upper_band, 2),
                "lower_band": round(lower_band, 2),
                "deviation_sigma": round(deviation_sigma, 4),
                "volume_ratio": round(volume_ratio, 4),
                "atr": round(atr, 4),
                "sl_pct_override": round(sl_pct, 6),
                "tp_pct_override": round(tp_pct, 6),
            },
        }
