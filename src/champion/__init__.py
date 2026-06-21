import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CHAMPION_CONFIG_PATH = Path("config/champions.yaml")


class ChampionRegistry:
    def __init__(self, config_path: Path | None = None):
        self._config_path = config_path or _CHAMPION_CONFIG_PATH
        self._champions: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._config_path.exists():
            self._champions = {}
            return
        try:
            with self._config_path.open("r") as f:
                data = yaml.safe_load(f) or {}
            self._champions = data.get("champions", {})
        except Exception as e:
            logger.error("Failed to load champions from %s: %s", self._config_path, e)
            self._champions = {}

    def _save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._config_path.open("w") as f:
                yaml.dump({"champions": self._champions}, f, default_flow_style=False)
        except Exception as e:
            logger.error("Failed to save champions to %s: %s", self._config_path, e)

    def get_champion(self, category: str) -> dict | None:
        return self._champions.get(category)

    def set_champion(
        self,
        category: str,
        strategy_name: str,
        params: dict[str, Any] | None = None,
        metrics: dict[str, float] | None = None,
    ) -> None:
        self._champions[category] = {
            "strategy_name": strategy_name,
            "params": params or {},
            "metrics": {
                "sharpe": metrics.get("sharpe", 0.0) if metrics else 0.0,
                "sortino": metrics.get("sortino", 0.0) if metrics else 0.0,
                "expectancy": metrics.get("expectancy", 0.0) if metrics else 0.0,
                "profit_factor": metrics.get("profit_factor", 0.0) if metrics else 0.0,
                "max_drawdown": metrics.get("max_drawdown", 0.0) if metrics else 0.0,
            },
            "promoted_date": datetime.now(UTC).isoformat(),
            "category": category,
        }
        self._save()

    def get_all_champions(self) -> dict[str, dict[str, Any]]:
        return dict(self._champions)

    def is_champion(self, category: str, strategy_name: str) -> bool:
        champion = self._champions.get(category)
        if champion is None:
            return False
        return champion.get("strategy_name") == strategy_name

    def promote(self, category: str, challenger: dict[str, Any]) -> bool:
        current = self._champions.get(category)
        if current is None:
            self.set_champion(
                category,
                challenger.get("strategy_name", ""),
                challenger.get("params"),
                challenger.get("metrics"),
            )
            return True
        return False


__all__ = ["ChampionRegistry"]
