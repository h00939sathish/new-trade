from pathlib import Path
from typing import Any

import yaml

from src.strategies.base import Strategy
from src.strategies import STRATEGY_REGISTRY



DEFAULT_CONFIG = {
    "strategies": {
        "momentum": {
            "enabled": True,
            "weight": 0.2,
            "params": {"short_window": 5, "long_window": 20, "threshold": 0.02},
        },
        "mean_reversion": {
            "enabled": True,
            "weight": 0.2,
            "params": {"window": 20, "entry_z": 2.0, "exit_z": 0.5},
        },
        "atr_breakout": {
            "enabled": True,
            "weight": 0.15,
            "params": {"window": 14, "multiplier": 2.0, "threshold": 0.01},
        },
        "bollinger": {
            "enabled": True,
            "weight": 0.1,
            "params": {"window": 20, "num_std": 2.0},
        },
        "rsi": {
            "enabled": True,
            "weight": 0.1,
            "params": {"window": 14, "oversold": 30.0, "overbought": 70.0},
        },
        "macd": {
            "enabled": True,
            "weight": 0.1,
            "params": {"fast": 12, "slow": 26, "signal": 9, "threshold": 0.0},
        },
        "volume": {
            "enabled": False,
            "weight": 0.1,
            "params": {"volume_window": 20, "price_window": 10, "volume_mult": 1.5},
        },
        "ichimoku": {
            "enabled": False,
            "weight": 0.05,
            "params": {"conversion": 9, "base": 26, "lagging": 52, "displacement": 26},
        },
        "stat_arb": {
            "enabled": False,
            "weight": 0.1,
            "params": {"primary_symbol": "TCS", "secondary_symbol": "INFY", "window": 60, "entry_z": 2.0, "exit_z": 0.5},
        },
        "vol_breakout": {
            "enabled": True,
            "weight": 0.15,
            "params": {"window": 20},
        },
        "ml_regime": {
            "enabled": False,
            "weight": 0.2,
            "params": {"lookback_window": 100, "prediction_horizon": 5},
        },
    },
}


def load_strategy_config(path: str | None = None) -> dict[str, Any]:
    if path is not None:
        p = Path(path)
        if p.exists():
            with p.open() as f:
                return yaml.safe_load(f)
    return dict(DEFAULT_CONFIG)


def build_strategies_from_config(config: dict[str, Any]) -> dict[str, Strategy]:
    raw = config.get("strategies", {})
    result: dict[str, Strategy] = {}
    weights: dict[str, float] = {}
    for name, cfg in raw.items():
        if not cfg.get("enabled", True):
            continue
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            continue
        params = cfg.get("params", {})
        strategy = cls(**params)
        result[name] = strategy
        weights[name] = cfg.get("weight", 1.0)
    return result
