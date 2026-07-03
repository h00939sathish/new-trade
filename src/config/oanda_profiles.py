OANDA_INSTRUMENT_PROFILES = {
    "XAU_USD": {
        "strategies": {
            "momentum": {
                "enabled": True,
                "weight": 0.6,
                "params": {"short_window": 5, "long_window": 20, "threshold": 0.0005},
            },
            "vol_breakout": {
                "enabled": True,
                "weight": 0.4,
                "params": {"window": 20},
            },
            "sideways_reversion": {
                "enabled": False,
                "weight": 0.0,
                "params": {},
            },
            "vwap_reversion": {
                "enabled": False,
                "weight": 0.0,
                "params": {},
            },
            "stat_arb": {
                "enabled": False,
                "weight": 0.0,
                "params": {},
            },
            "ema200_regime_gate": {
                "enabled": True,
                "weight": 0.0,
                "params": {"lookback": 100},
            },
            "adx_regime_filter": {
                "enabled": True,
                "weight": 0.0,
                "params": {"period": 14},
            },
        },
        "instrument_meta": {
            "asset_class": "COMMODITY",
            "currency": "USD",
            "pip_location": -1,
            "trade_units_precision": 0,
            "minimum_trade_size": 1,
            "max_spread": 0.50,
        },
    },
    "EUR_USD": {
        "strategies": {
            "momentum": {
                "enabled": True,
                "weight": 0.5,
                "params": {"short_window": 5, "long_window": 20, "threshold": 0.0003},
            },
            "sideways_reversion": {
                "enabled": True,
                "weight": 0.3,
                "params": {"rsi_window": 14, "bb_window": 20, "bb_std": 2.0, "atr_window": 14},
            },
            "vol_breakout": {
                "enabled": True,
                "weight": 0.2,
                "params": {"window": 20},
            },
            "vwap_reversion": {
                "enabled": False,
                "weight": 0.0,
                "params": {},
            },
            "stat_arb": {
                "enabled": False,
                "weight": 0.0,
                "params": {},
            },
            "ema200_regime_gate": {
                "enabled": True,
                "weight": 0.0,
                "params": {"lookback": 100},
            },
            "adx_regime_filter": {
                "enabled": True,
                "weight": 0.0,
                "params": {"period": 14},
            },
        },
        "instrument_meta": {
            "asset_class": "CURRENCY",
            "currency": "USD",
            "pip_location": -4,
            "trade_units_precision": 0,
            "minimum_trade_size": 1,
            "max_spread": 0.0003,
        },
    },
}


def load_oanda_profile(instrument: str) -> dict:
    from src.config.strategy_config import DEFAULT_CONFIG
    profile = OANDA_INSTRUMENT_PROFILES.get(instrument, {})
    strategies = profile.get("strategies", {})
    config = __import__("copy").deepcopy(DEFAULT_CONFIG)
    for name, overrides in strategies.items():
        if name in config["strategies"]:
            config["strategies"][name].update(overrides)
    return config
