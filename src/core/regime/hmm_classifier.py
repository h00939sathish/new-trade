import logging
from enum import StrEnum

import numpy as np

try:
    from hmmlearn.hmm import GaussianHMM

    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False

logger = logging.getLogger("core.regime.hmm")


class HMMState(StrEnum):
    TRENDING = "TRENDING"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOL = "HIGH_VOL"
    CRISIS = "CRISIS"


class HMMRegimeClassifier:
    """
    Hidden Markov Model Regime Classifier.
    - States: TRENDING, SIDEWAYS, HIGH_VOL, CRISIS
    - Features: Returns, ATR, Volume, Realized Volatility
    """

    def __init__(self, lookback: int = 252, n_components: int = 4):
        self.lookback = lookback
        self.n_components = n_components
        self.model = None
        if HMM_AVAILABLE:
            self.model = GaussianHMM(
                n_components=self.n_components, covariance_type="full", n_iter=100
            )

    def _extract_features(
        self, prices: list[float], highs: list[float], lows: list[float], volumes: list[float]
    ) -> np.ndarray:
        ret = np.diff(prices) / prices[:-1]

        atr = []
        for j in range(1, len(prices)):
            tr = max(
                highs[j] - lows[j], abs(highs[j] - prices[j - 1]), abs(lows[j] - prices[j - 1])
            )
            atr.append(tr / prices[j - 1])  # Normalized ATR

        vol = np.array(volumes[1:])
        vol = (vol - np.mean(vol)) / (np.std(vol) + 1e-8)  # Normalize volume

        # Realized Volatility (rolling 20 days)
        realized_vol = []
        for i in range(len(ret)):
            if i < 20:
                realized_vol.append(np.std(ret[: i + 1]))
            else:
                realized_vol.append(np.std(ret[i - 19 : i + 1]))

        return np.column_stack([ret, atr, vol, realized_vol])

    def fit_predict(
        self, prices: list[float], highs: list[float], lows: list[float], volumes: list[float]
    ) -> dict[str, float]:
        """
        Outputs Regime Probability Vector.
        """
        if len(prices) < self.lookback + 1:
            # Default vector
            return {s.value: 0.25 for s in HMMState}

        recent_p = prices[-self.lookback :]
        recent_h = highs[-self.lookback :]
        recent_l = lows[-self.lookback :]
        recent_v = volumes[-self.lookback :]

        if not HMM_AVAILABLE:
            # Fallback heuristic if hmmlearn is not installed
            ret = np.diff(recent_p) / recent_p[:-1]
            realized_vol = np.std(ret) * np.sqrt(252)
            trend = abs(recent_p[-1] - recent_p[0]) / recent_p[0]

            probs = {s.value: 0.1 for s in HMMState}
            if realized_vol > 0.3:
                probs[HMMState.CRISIS.value] = 0.7
            elif realized_vol > 0.15:
                probs[HMMState.HIGH_VOL.value] = 0.7
            elif trend > 0.1:
                probs[HMMState.TRENDING.value] = 0.7
            else:
                probs[HMMState.SIDEWAYS.value] = 0.7

            return probs

        features = self._extract_features(recent_p, recent_h, recent_l, recent_v)

        try:
            self.model.fit(features)
            self.model.predict(features)

            # Predict probabilities for the most recent observation
            probs = self.model.predict_proba(features)[-1]

            # Note: HMM states are permutation invariant. We would ideally map them
            # based on cluster means (e.g. highest variance = CRISIS, etc.)
            # For simplicity in this implementation, we map based on expected properties
            # Sort by variance of returns (column 0) to separate Volatile from Calm

            # Heuristic mapping
            # This is a placeholder for a robust state mapping logic
            mapped_probs = {
                HMMState.SIDEWAYS.value: probs[0],
                HMMState.TRENDING.value: probs[1],
                HMMState.HIGH_VOL.value: probs[2],
                HMMState.CRISIS.value: probs[3],
            }
            return mapped_probs
        except Exception as e:
            logger.error("HMM fit failed: %s", e)
            return {s.value: 0.25 for s in HMMState}
