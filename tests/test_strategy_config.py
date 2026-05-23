import tempfile
from pathlib import Path

import yaml

from src.config.strategy_config import (
    STRATEGY_REGISTRY,
    build_strategies_from_config,
    load_strategy_config,
)


class TestStrategyConfig:
    def test_default_config_has_all_strategies(self):
        cfg = load_strategy_config()
        assert "strategies" in cfg
        for name in STRATEGY_REGISTRY:
            assert name in cfg["strategies"]

    def test_all_strategies_have_config(self):
        cfg = load_strategy_config()
        for name, scfg in cfg["strategies"].items():
            assert "enabled" in scfg
            assert "weight" in scfg
            assert "params" in scfg

    def test_build_enabled_strategies_from_default(self):
        cfg = load_strategy_config()
        strategies = build_strategies_from_config(cfg)
        for name, scfg in cfg["strategies"].items():
            if scfg.get("enabled", True):
                assert name in strategies

    def test_build_respects_disabled(self):
        cfg = {"strategies": {"momentum": {"enabled": False, "params": {}}}}
        strategies = build_strategies_from_config(cfg)
        assert "momentum" not in strategies

    def test_build_with_custom_params(self):
        cfg = {
            "strategies": {
                "momentum": {
                    "enabled": True,
                    "weight": 1.0,
                    "params": {"short_window": 10, "long_window": 30, "threshold": 0.05},
                }
            }
        }
        strategies = build_strategies_from_config(cfg)
        s = strategies["momentum"]
        assert s.short_window == 10
        assert s.long_window == 30
        assert s.threshold == 0.05

    def test_load_from_file(self):
        data = {
            "strategies": {
                "rsi": {
                    "enabled": True,
                    "weight": 1.0,
                    "params": {"window": 7, "oversold": 25.0, "overbought": 75.0},
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            f.flush()
            cfg = load_strategy_config(f.name)
            assert cfg["strategies"]["rsi"]["params"]["window"] == 7
        Path(f.name).unlink(missing_ok=True)

    def test_load_missing_file_returns_default(self):
        cfg = load_strategy_config("/nonexistent/strategies.yaml")
        assert "strategies" in cfg
        assert "momentum" in cfg["strategies"]

    def test_weights_in_built_strategies(self):
        cfg = load_strategy_config()
        strategies = build_strategies_from_config(cfg)
        for name, scfg in cfg["strategies"].items():
            if scfg.get("enabled", True):
                assert name in strategies
