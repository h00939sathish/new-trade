import numpy as np


class TripleBarrierMetaLabeler:
    """
    Triple Barrier Meta Labeling Model.
    - Primary Strategy generates signal.
    - Meta Model predicts SUCCESS or FAILURE of that signal.
    - Outputs Position Multiplier: 0.25x, 0.5x, 1.0x, 1.5x
    """

    def __init__(self, model=None):
        # The model would ideally be a pre-trained RandomForestClassifier or similar from scikit-learn
        self.model = model

    def _extract_features(
        self,
        regime: str,
        volatility: float,
        momentum: float,
        volume_zscore: float,
        recent_win_rate: float,
    ) -> np.ndarray:
        # Encode regime as integer
        regime_map = {
            "TRENDING": 1,
            "SIDEWAYS": 0,
            "HIGH_VOL": -1,
            "CRISIS": -2,
            "MEAN_REVERSION_ONLY": 0,
        }
        reg_val = regime_map.get(regime, 0)

        return np.array([[reg_val, volatility, momentum, volume_zscore, recent_win_rate]])

    def predict_multiplier(
        self,
        primary_signal_confidence: float,
        regime: str,
        volatility: float,
        momentum: float,
        volume_zscore: float,
        recent_win_rate: float,
    ) -> float:
        """
        Returns a position multiplier based on meta-labeling prediction.
        """
        features = self._extract_features(
            regime, volatility, momentum, volume_zscore, recent_win_rate
        )

        if self.model:
            # If we have a trained model, predict probability of SUCCESS
            try:
                prob_success = self.model.predict_proba(features)[0][
                    1
                ]  # Assuming binary classifier (0=FAIL, 1=SUCCESS)
            except Exception:
                prob_success = primary_signal_confidence
        else:
            # Fallback heuristic if no ML model is trained yet
            prob_success = primary_signal_confidence
            # Adjust probability based on favorable conditions
            if recent_win_rate > 0.6:
                prob_success += 0.1
            if recent_win_rate < 0.4:
                prob_success -= 0.1
            if regime in ("HIGH_VOL", "CRISIS"):
                prob_success -= 0.15

        prob_success = max(0.0, min(1.0, prob_success))

        # Output position multiplier based on predicted probability of success
        if prob_success >= 0.8:
            return 1.5
        elif prob_success >= 0.6:
            return 1.0
        elif prob_success >= 0.4:
            return 0.5
        else:
            return 0.25
