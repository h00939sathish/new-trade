from pathlib import Path
from typing import Any

import yaml

from src.strategies import STRATEGY_REGISTRY
from src.strategies.base import Strategy

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
            "enabled": True,
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
        "microstructure": {
            "enabled": True,
            "weight": 0.15,
            "params": {"ofi_window": 20, "threshold": 1.5},
        },
        "orb": {
            "enabled": True,
            "weight": 0.15,
            "params": {"volume_multiplier": 1.2, "atr_window": 14},
        },
        "vol_compression": {
            "enabled": True,
            "weight": 0.15,
            "params": {"bb_window": 20, "bb_std": 2.0, "lookback": 100, "percentile_threshold": 20.0, "atr_window": 14},
        },
        "tsmom": {
            "enabled": True,
            "weight": 0.15,
            "params": {"target_volatility": 0.10, "horizons": [60, 120, 250]},
        },
        "sideways_reversion": {
            "enabled": True,
            "weight": 0.15,
            "params": {"rsi_window": 14, "bb_window": 20, "bb_std": 2.0, "atr_window": 14},
        },
        "pca_statarb": {
            "enabled": True,
            "weight": 0.15,
            "params": {"window": 60, "n_components": 1, "entry_z": 2.0, "exit_z": 0.5},
        },
    },
}


def load_strategy_config(path: str | None = None) -> dict[str, Any]:
    if path is not None:
        p = Path(path)
        if p.exists():
            with p.open() as f:
                return yaml.safe_load(f)
    import copy
    return copy.deepcopy(DEFAULT_CONFIG)


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
