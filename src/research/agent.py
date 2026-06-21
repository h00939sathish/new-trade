import itertools
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from src.agents.base import BaseAgent
from src.config.settings import settings

logger = logging.getLogger("agent.research")

STRATEGIES_PATH = Path("config/strategies.yaml")
HYPOTHESIS_COUNTER_PATH = Path("state/research_hypothesis_counter.yaml")
REPORTS_DIR = Path("reports/research")

SEARCH_SPACES: dict[str, dict[str, list[Any]]] = {
    "momentum": {
        "short_window": [3, 5, 8],
        "long_window": [15, 20, 25],
        "threshold": [0.01, 0.02, 0.03],
    },
    "mean_reversion": {
        "window": [15, 20, 25],
        "entry_z": [1.5, 2.0, 2.5],
        "exit_z": [0.3, 0.5, 0.7],
    },
    "bollinger": {
        "window": [15, 20, 25],
        "num_std": [1.5, 2.0, 2.5],
    },
    "rsi": {
        "window": [10, 14, 18],
        "oversold": [25.0, 30.0, 35.0],
        "overbought": [65.0, 70.0, 75.0],
    },
    "macd": {
        "fast": [10, 12, 14],
        "slow": [24, 26, 28],
        "signal": [7, 9, 11],
    },
    "atr_breakout": {
        "window": [10, 14, 18],
        "multiplier": [1.5, 2.0, 2.5],
        "threshold": [0.005, 0.01, 0.015],
    },
}


@dataclass
class Hypothesis:
    strategy: str
    params: dict[str, Any]
    expected_sharpe_improvement: float
    rationale: str
    timestamp: str
    baseline_sharpe: float = 0.0
    proposed_sharpe: float = 0.0


class ResearchAgent(BaseAgent):
    def __init__(
        self,
        event_store=None,
        strategy_config_path: str | None = None,
        backtest_data_provider: Any = None,
        llm_client: Any | None = None,
    ):
        super().__init__("research_agent", event_store=event_store)
        self._strategy_config_path = (
            Path(strategy_config_path) if strategy_config_path else STRATEGIES_PATH
        )
        self._backtest_data_provider = backtest_data_provider
        self._llm_client = llm_client or GeminiClient()
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        HYPOTHESIS_COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)

    async def on_start(self) -> None:
        self.logger.info("Research Agent initializing — AI research only, no trading capability")

    async def on_stop(self) -> None:
        self.logger.info("Research Agent stopping")

    async def on_event(self, event: Any) -> None:
        pass

    async def generate_hypothesis(self, strategy_name: str) -> Hypothesis | None:
        if not self._check_weekly_limit():
            self.logger.warning("Weekly hypothesis limit reached — skipping generation")
            return None

        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(self._strategy_config_path))
        strat_cfg = cfg.get("strategies", {}).get(strategy_name)
        if not strat_cfg:
            self.logger.warning("Strategy %s not found in config", strategy_name)
            return None

        baseline_result = await self._run_backtest()
        if not baseline_result:
            return None

        hypothesis = await self._llm_generate(strategy_name, baseline_result)
        if not hypothesis:
            hypothesis = self._fallback_hypothesis(strategy_name, baseline_result)

        if not hypothesis:
            return None

        mutated_result = await self._evaluate_hypothesis(hypothesis)
        if not mutated_result or mutated_result.total_trades < 3:
            return None

        improvement = mutated_result.sharpe_ratio - baseline_result.sharpe_ratio
        if improvement <= 0:
            return None

        h = Hypothesis(
            strategy=hypothesis["strategy"],
            params=hypothesis["params"],
            expected_sharpe_improvement=improvement,
            rationale=hypothesis["rationale"],
            timestamp=datetime.now(UTC).isoformat(),
            baseline_sharpe=baseline_result.sharpe_ratio,
            proposed_sharpe=mutated_result.sharpe_ratio,
        )

        self._increment_counter()
        await self._write_hypothesis_report(h)
        return h

    async def run_research_scan(self) -> list[Hypothesis]:
        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(self._strategy_config_path))
        hypotheses: list[Hypothesis] = []

        for strat_name, strat_cfg in cfg.get("strategies", {}).items():
            if not strat_cfg.get("enabled", True):
                continue
            h = await self._grid_search_strategy(strat_name)
            if h:
                hypotheses.append(h)

        return hypotheses

    async def _grid_search_strategy(self, strategy_name: str) -> Hypothesis | None:
        if not self._check_weekly_limit():
            return None

        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(self._strategy_config_path))
        strat_cfg = cfg.get("strategies", {}).get(strategy_name)
        if not strat_cfg:
            return None

        baseline_result = await self._run_backtest()
        if not baseline_result:
            return None

        space = SEARCH_SPACES.get(strategy_name)
        if not space:
            return None

        best_sharpe = baseline_result.sharpe_ratio
        best_params = None

        keys, values = zip(*space.items())
        for val_combination in itertools.product(*values):
            params = dict(zip(keys, val_combination))
            current_params = strat_cfg.get("params", {})
            if all(current_params.get(k) == v for k, v in params.items()):
                continue

            override = {strategy_name: {"params": params, "enabled": True}}
            res = await self._run_backtest(strategy_config_override=override)
            if res and res.sharpe_ratio > best_sharpe:
                best_sharpe = res.sharpe_ratio
                best_params = params

        if best_params and best_sharpe > baseline_result.sharpe_ratio * 1.05:
            improvement = best_sharpe - baseline_result.sharpe_ratio
            h = Hypothesis(
                strategy=strategy_name,
                params=best_params,
                expected_sharpe_improvement=improvement,
                rationale=f"Grid search parameter optimization: Sharpe improved from {baseline_result.sharpe_ratio:.3f} to {best_sharpe:.3f}",
                timestamp=datetime.now(UTC).isoformat(),
                baseline_sharpe=baseline_result.sharpe_ratio,
                proposed_sharpe=best_sharpe,
            )
            self._increment_counter()
            await self._write_hypothesis_report(h)
            return h
        return None

    async def _llm_generate(self, strategy_name: str, baseline_result: Any) -> dict[str, Any] | None:
        return await self._llm_client.generate_hypothesis(baseline_result, [])

    def _fallback_hypothesis(self, strategy_name: str, baseline_result: Any) -> dict[str, Any] | None:
        if baseline_result.total_trades < 5:
            return None
        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(self._strategy_config_path))
        sc = cfg.get("strategies", {}).get(strategy_name)
        if not sc:
            return None
        params = sc.get("params", {})
        mutated = {}
        for k, v in params.items():
            if isinstance(v, (int, float)):
                mult = 1.1 if baseline_result.sharpe_ratio < 0.5 else 0.9
                mutated[k] = round(v * mult, 1)
        if mutated:
            return {
                "strategy": strategy_name,
                "params": mutated,
                "rationale": "fallback heuristic adjustment",
            }
        return None

    async def _evaluate_hypothesis(self, hypothesis: dict[str, Any]) -> Any:
        strategy_name = hypothesis.get("strategy")
        param_changes = hypothesis.get("params", {})
        if not strategy_name or not param_changes:
            return None
        override = {strategy_name: {"params": param_changes, "enabled": True}}
        return await self._run_backtest(strategy_config_override=override)

    async def _run_backtest(self, strategy_config_override: dict[str, Any] | None = None) -> Any:
        try:
            from src.backtest.engine import BacktestEngine
            from src.config.strategy_config import (
                build_strategies_from_config,
                load_strategy_config,
            )

            cfg = load_strategy_config(str(self._strategy_config_path))
            if strategy_config_override:
                cfg["strategies"].update(strategy_config_override)

            strategies = build_strategies_from_config(cfg)
            if not strategies:
                self.logger.warning("No strategies enabled for backtest")
                return None

            engine = BacktestEngine(
                strategies=list(strategies.values()),
                initial_capital=settings.reflection_initial_capital,
            )

            ticks = await self._get_backtest_data()
            if not ticks:
                self.logger.warning("No backtest data available")
                return None

            return await engine.run(ticks)
        except Exception as e:
            self.logger.error("Backtest failed: %s", e, exc_info=True)
            return None

    async def _get_backtest_data(self) -> list[dict[str, Any]]:
        provider = self._backtest_data_provider
        if provider and hasattr(provider, "get_backtest_ticks"):
            return await provider.get_backtest_ticks()
        from src.connectors.backtest_provider import generate_synthetic_ticks

        return generate_synthetic_ticks()

    async def _write_hypothesis_report(self, hypothesis: Hypothesis) -> None:
        date_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        safe_name = hypothesis.strategy.replace(" ", "_").lower()
        path = REPORTS_DIR / f"{date_str}_{safe_name}.md"
        content = (
            f"# Research Hypothesis\n\n"
            f"- **Strategy:** {hypothesis.strategy}\n"
            f"- **Timestamp:** {hypothesis.timestamp}\n"
            f"- **Parameters:** {json.dumps(hypothesis.params, indent=2)}\n"
            f"- **Baseline Sharpe:** {hypothesis.baseline_sharpe:.4f}\n"
            f"- **Proposed Sharpe:** {hypothesis.proposed_sharpe:.4f}\n"
            f"- **Expected Sharpe Improvement:** {hypothesis.expected_sharpe_improvement:.4f}\n"
            f"- **Rationale:** {hypothesis.rationale}\n\n"
            "---\n"
            "*This hypothesis is a suggestion only — it does not modify any configuration.*\n"
        )
        path.write_text(content)
        self.logger.info("Hypothesis report written to %s", path)

    def _check_weekly_limit(self) -> bool:
        if not HYPOTHESIS_COUNTER_PATH.exists():
            return True
        try:
            data = yaml.safe_load(HYPOTHESIS_COUNTER_PATH.read_text()) or {}
        except Exception:
            return True
        current_week = datetime.now(UTC).isocalendar()
        week_key = f"{current_week[0]}-W{current_week[1]}"
        entry = data.get(week_key, {})
        count = entry.get("count", 0)
        return count < 5

    def _increment_counter(self) -> None:
        data = {}
        if HYPOTHESIS_COUNTER_PATH.exists():
            try:
                data = yaml.safe_load(HYPOTHESIS_COUNTER_PATH.read_text()) or {}
            except Exception:
                data = {}
        current_week = datetime.now(UTC).isocalendar()
        week_key = f"{current_week[0]}-W{current_week[1]}"
        entry = data.get(week_key, {"count": 0})
        entry["count"] = entry.get("count", 0) + 1
        data[week_key] = entry
        HYPOTHESIS_COUNTER_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({"mode": "research_only", "no_trading": True})
        return base


class GeminiClient:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")

    async def generate_hypothesis(
        self,
        current_result: Any,
        mutation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        if not self._api_key:
            return None

        prompt = self._build_prompt(current_result, mutation_history or [])
        try:
            return await self._call_gemini(prompt)
        except Exception as e:
            logging.getLogger("research.llm").warning("Gemini API call failed: %s", e)
            return None

    async def _call_gemini(self, prompt: str) -> dict[str, Any] | None:
        import httpx

        url = f"{self.BASE_URL}/gemini-2.0-flash:generateContent?key={self._api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 512,
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
        text = parts[0].get("text", "") if parts else ""
        return self._parse_response(text)

    def _build_prompt(self, result: Any, history: list[dict[str, Any]]) -> str:
        strat_lines = []
        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(STRATEGIES_PATH))
        for name, sc in cfg.get("strategies", {}).items():
            if sc.get("enabled", True):
                line = f"  {name}: params={sc['params']}, weight={sc.get('weight', 1.0)}"
                strat_lines.append(line)

        history_lines = []
        for h in history[-5:]:
            hyp = h.get("hypothesis", {})
            params_str = hyp.get("params")
            rat = hyp.get("rationale", "")[:60]
            line = (
                f"  - strategy={hyp.get('strategy')} params={params_str}"
                f" rationale={rat} applied={h.get('applied')}"
            )
            history_lines.append(line)

        return (
            f"You are a quantitative trading strategy optimizer for Indian markets (NSE/BSE).\n\n"
            f"Current strategy config:\n{chr(10).join(strat_lines)}\n\n"
            f"Last backtest:\n"
            f"  Trades: {result.total_trades}\n"
            f"  Win rate: {result.win_rate:.1%}\n"
            f"  Sharpe ratio: {result.sharpe_ratio:.3f}\n"
            f"  PnL: {result.total_pnl:.2f}\n"
            f"  Max drawdown: {result.max_drawdown:.1%}\n"
            f"  Profit factor: {result.profit_factor:.2f}\n\n"
            f"Recent mutation history:\n"
            f"{chr(10).join(history_lines) if history_lines else '  (none)'}\n\n"
            "Suggest ONE strategy parameter improvement to enhance performance.\n"
            "Return JSON only:\n"
            '{"strategy": "strategy_name", "params": {"param1": new_value}, '
            '"rationale": "why this change"}\n'
            "Pick a strategy name from the config above. "
            "Change only 1-2 numeric params slightly (+-10-30%).\n"
            "Do not change enabling/disabling or weight. Only suggest param changes.\n"
            "Return ONLY valid JSON, no markdown."
        )

    def _parse_response(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logging.getLogger("research.llm").warning("Failed to parse Gemini response: %s", text[:200])
            return None

    @property
    def logger(self):
        return logging.getLogger("research.llm")
