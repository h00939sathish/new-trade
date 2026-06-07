from typing import Any

import numpy as np

from src.strategies.base import Strategy

try:
    from sklearn.ensemble import RandomForestClassifier

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class MLRegimeStrategy(Strategy):
    """
    Machine Learning Strategy using Random Forest to predict direction.
    Uses rolling training window to adapt to regimes.
    """

    def __init__(
        self,
        lookback_window: int = 100,
        prediction_horizon: int = 5,
    ):
        self.name = "ml_regime"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.lookback_window = lookback_window
        self.prediction_horizon = prediction_horizon
        self.model = RandomForestClassifier(n_estimators=50, max_depth=3, random_state=42)
        self.is_trained = False

    def _extract_features(self, prices: list[float]) -> np.ndarray:
        # Simple feature set: 1-period return, 5-period return, 10-period volatility
        features = []
        for i in range(10, len(prices)):
            r1 = (prices[i] - prices[i - 1]) / prices[i - 1]
            r5 = (prices[i] - prices[i - 5]) / prices[i - 5]
            vol10 = np.std(prices[i - 10 : i]) / prices[i - 10]
            features.append([r1, r5, vol10])
        return np.array(features)

    def _create_labels(self, prices: list[float]) -> np.ndarray:
        # Predict if price will be higher in 'prediction_horizon' periods
        labels = []
        for i in range(10, len(prices) - self.prediction_horizon):
            future_return = (prices[i + self.prediction_horizon] - prices[i]) / prices[i]
            # 1 for UP, 0 for DOWN
            labels.append(1 if future_return > 0 else 0)
        return np.array(labels)

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
    ) -> dict[str, Any] | None:
        if not SKLEARN_AVAILABLE:
            return None

        if len(prices) < self.lookback_window:
            return None

        # Re-train model periodically (every evaluation for simplicity, in reality batch it)
        # We need N samples + prediction horizon
        train_prices = prices[-self.lookback_window :]

        X = self._extract_features(train_prices)
        y = self._create_labels(train_prices)

        # We must truncate X to match y length (we lose the last 'prediction_horizon' samples)
        if len(X) <= self.prediction_horizon or len(y) == 0:
            return None

        X_train = X[: -self.prediction_horizon]

        # Ensure we have both classes
        if len(np.unique(y)) < 2:
            return None

        self.model.fit(X_train, y)
        self.is_trained = True

        # Predict current state
        # The latest feature vector uses the most recent prices
        X_current = self._extract_features(prices[-(10 + 1) :])
        if len(X_current) == 0:
            return None

        latest_feature = X_current[-1].reshape(1, -1)

        prob = self.model.predict_proba(latest_feature)[0]
        pred_class = np.argmax(prob)
        confidence = float(prob[pred_class])

        # Only trade if model is reasonably confident
        if confidence < 0.55:
            return None

        direction = "long" if pred_class == 1 else "short"

        return {
            "direction": direction,
            "confidence": confidence,
            "price": prices[-1],
            "features": {"ml_prob_up": float(prob[1]), "ml_prob_down": float(prob[0])},
        }
