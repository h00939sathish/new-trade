import logging
from collections import deque

import numpy as np
import pandas as pd

from src.strategies.base import Strategy
from src.strategies.drl_env import build_observation, compute_features

logger = logging.getLogger(__name__)


class DRLStrategy(Strategy):
    """Wraps a pre-trained Stable Baselines 3 model as a plug-in strategy."""

    def __init__(
        self,
        model_path: str = "models/drl_agent.zip",
        lookback: int = 60,
        action_repeats: int = 3,
        hold_action: int = 1,
        confidence_scale: float = 0.8,
    ):
        self.name = "drl_ensemble"
        self.data_type = "candle"
        self.timeframe = "minute"
        self._model_path = model_path
        self._lookback = lookback
        self._action_repeats = action_repeats
        self._hold_action = hold_action
        self._confidence_scale = confidence_scale
        self._model = None
        self._step_counter = 0
        self._last_action = 1
        self._buf_close: deque[float] = deque(maxlen=500)
        self._buf_high: deque[float] = deque(maxlen=500)
        self._buf_low: deque[float] = deque(maxlen=500)
        self._buf_volume: deque[float] = deque(maxlen=500)

    def _lazy_load(self) -> None:
        if self._model is not None:
            return
        try:
            from stable_baselines3 import PPO

            self._model = PPO.load(self._model_path)
            logger.info("DRL model loaded from %s", self._model_path)
        except ImportError:
            logger.warning(
                "stable-baselines3 not installed — DRL strategy disabled. "
                "Install with: pip install 'trading-system[ml]'"
            )
        except FileNotFoundError:
            logger.warning(
                "DRL model not found at %s — strategy will emit no signals",
                self._model_path,
            )

    def _build_obs(self) -> np.ndarray | None:
        if len(self._buf_close) < self._lookback + 20:
            return None

        mini_df = pd.DataFrame({
            "close": list(self._buf_close),
            "high": list(self._buf_high) if len(self._buf_high) == len(self._buf_close) else list(self._buf_close),
            "low": list(self._buf_low) if len(self._buf_low) == len(self._buf_close) else list(self._buf_close),
            "volume": list(self._buf_volume) if len(self._buf_volume) == len(self._buf_close) else [1.0] * len(self._buf_close),
        })
        features = compute_features(mini_df)
        obs = build_observation(
            features=features,
            current_step=len(mini_df) - 1,
            lookback=self._lookback,
            total_steps=len(mini_df),
        )
        return obs

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[object] | None = None,
    ) -> dict[str, object] | None:
        self._lazy_load()
        if self._model is None:
            return None

        if len(prices) > len(self._buf_close):
            new_prices = prices[len(self._buf_close):]
            self._buf_close.extend(new_prices)
            if volumes and len(volumes) > len(self._buf_volume):
                self._buf_volume.extend(volumes[len(self._buf_volume):])
            if highs and len(highs) > len(self._buf_high):
                self._buf_high.extend(highs[len(self._buf_high):])
            if lows and len(lows) > len(self._buf_low):
                self._buf_low.extend(lows[len(self._buf_low):])

        obs = self._build_obs()
        if obs is None:
            return None

        self._step_counter += 1

        should_predict = self._step_counter <= 1 or self._step_counter % self._action_repeats == 0

        if not should_predict:
            if self._last_action == self._hold_action:
                return None
            direction = "long" if self._last_action > self._hold_action else "short"
            return {
                "direction": direction,
                "confidence": min(self._confidence_scale, 0.7),
                "price": prices[-1],
                "features": {"drl_action": int(self._last_action), "action_repeat": True},
            }

        try:
            action, _ = self._model.predict(obs, deterministic=True)
        except Exception as exc:
            logger.warning("DRL predict failed for %s: %s", instrument, exc)
            return None

        self._last_action = int(action) if hasattr(action, "__len__") else int(action)

        if self._last_action == self._hold_action:
            return None

        direction = "long" if self._last_action > self._hold_action else "short"

        return {
            "direction": direction,
            "confidence": self._confidence_scale,
            "price": prices[-1],
            "features": {
                "drl_action": self._last_action,
                "model_path": self._model_path,
            },
        }
