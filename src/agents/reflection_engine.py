import json
import logging
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.connectors.backtest_provider import generate_synthetic_ticks
from src.schemas.events import (
    Event,
    EventType,
    FillEvent,
    SystemEvent,
)

logger = logging.getLogger("agent.reflection_engine")

STRATEGIES_PATH = Path("config/strategies.yaml")


class ReflectionEngineAgent(BaseAgent):
    def __init__(
        self,
        event_store=None,
        strategy_config_path: str | None = None,
        backtest_data_provider: Any = None,
        llm_client: Any = None,
    ):
        super().__init__("reflection_engine", event_store=event_store)
        self._strategy_config_path = (
            Path(strategy_config_path) if strategy_config_path else STRATEGIES_PATH
        )
        self._backtest_data_provider = backtest_data_provider
        self._llm_client = llm_client or GeminiClient()
        self._fill_buffer: list[FillEvent] = []
        self._baseline_pnl = 0.0
        self._mutation_history: list[dict[str, Any]] = []
        self._last_evaluation_pnl = 0.0
        self._last_baseline_result: Any = None
        self._pending_mutation: dict[str, Any] | None = None

        self._candidates: dict[str, Any] = {}
        self._candidates_path = Path("config/candidates.yaml")
        self._load_candidates()

    def _load_candidates(self) -> None:
        if self._candidates_path.exists():
            with self._candidates_path.open() as f:
                self._candidates = yaml.safe_load(f) or {}
            self.logger.info("Loaded %d shadow candidates", len(self._candidates))

    def _save_candidates(self) -> None:
        self._candidates_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._candidates_path.with_suffix(".yaml.tmp")
        with tmp.open("w") as f:
            yaml.dump(self._candidates, f, default_flow_style=False, sort_keys=False)
        tmp.rename(self._candidates_path)

    def _inject_candidates(self) -> None:
        system = getattr(self, "system", None)
        if not system or not hasattr(system, "strategy_gen"):
            return
        from src.config.strategy_config import STRATEGY_REGISTRY

        for cand_id, cand_data in self._candidates.items():
            if cand_data.get("status") == "active":
                strat_name = cand_data.get("strategy")
                strat_class = STRATEGY_REGISTRY.get(strat_name)
                if strat_class:
                    strat = strat_class(name=cand_id, **cand_data.get("params", {}))
                    system.strategy_gen.register_candidate_strategy(strat)

    async def on_start(self) -> None:
        self.logger.info("Reflection Engine Agent initializing")
        self.subscribe(EventType.FILL)
        self.subscribe(EventType.PORTFOLIO_UPDATE)
        self.subscribe(EventType.CANDIDATE_SIGNAL)
        self.subscribe_system()
        self._inject_candidates()
        self.logger.info("Evaluation window: %d fills", settings.reflection_eval_window)

    async def on_stop(self) -> None:
        self.logger.info("Reflection Engine Agent stopping")

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.FILL:
                await self._on_fill(event)
            case EventType.PORTFOLIO_UPDATE:
                self._baseline_pnl = event.data.get("pnl", 0.0)
            case EventType.CANDIDATE_SIGNAL:
                await self._on_candidate_signal(event)
            case EventType.SYSTEM_HEALTH:
                pass

    async def _on_fill(self, event: Event) -> None:
        fill = self._to_fill_event(event)
        self._fill_buffer.append(fill)
        self.logger.debug(
            "Fill recorded: %s %d@%.2f",
            fill.side.value,
            fill.fill_quantity,
            fill.fill_price,
        )

        if len(self._fill_buffer) >= settings.reflection_eval_window:
            await self._run_reflection_cycle()

    async def _on_candidate_signal(self, event: Event) -> None:
        cand_id = event.data.get("strategy")
        if not cand_id or cand_id not in self._candidates:
            return

        cand = self._candidates[cand_id]
        if cand.get("status") != "active":
            return

        direction = event.data.get("direction")
        price = event.data.get("price")
        if not price or direction == "neutral":
            return

        current_pos = cand.get("position", 0)
        from src.risk.costs import TransactionCostModel

        # Basic flat model for estimation
        cost_model = TransactionCostModel(brokerage_pct=0.0003, slippage_bps=5.0)

        # Simple stop-and-reverse shadow execution
        qty = 100  # fixed paper trade quantity for evaluation

        if direction == "long" and current_pos <= 0:
            if current_pos < 0:
                # Cover short
                entry_price = cand.get("avg_price", price)
                pnl = (entry_price - price) * abs(current_pos)
                cost = cost_model.total_cost("buy", abs(current_pos), price)
                cand["realized_pnl"] = cand.get("realized_pnl", 0.0) + pnl - cost
                cand["trades"] = cand.get("trades", 0) + 1
            # Go long
            cand["position"] = qty
            cand["avg_price"] = price
            cand["realized_pnl"] -= cost_model.total_cost("buy", qty, price)
            self._save_candidates()
            self.logger.info("Candidate %s went LONG at %.2f", cand_id, price)

        elif direction == "short" and current_pos >= 0:
            if current_pos > 0:
                # Sell long
                entry_price = cand.get("avg_price", price)
                pnl = (price - entry_price) * abs(current_pos)
                cost = cost_model.total_cost("sell", abs(current_pos), price)
                cand["realized_pnl"] = cand.get("realized_pnl", 0.0) + pnl - cost
                cand["trades"] = cand.get("trades", 0) + 1
            # Go short
            cand["position"] = -qty
            cand["avg_price"] = price
            cand["realized_pnl"] -= cost_model.total_cost("sell", qty, price)
            self._save_candidates()
            self.logger.info("Candidate %s went SHORT at %.2f", cand_id, price)

    def _to_fill_event(self, event: Event) -> FillEvent:
        return FillEvent(**event.model_dump())

    async def _run_reflection_cycle(self) -> None:
        self.logger.info(
            "Reflection cycle triggered (%d fills accumulated)",
            len(self._fill_buffer),
        )
        self._fill_buffer = self._fill_buffer[settings.reflection_eval_window :]

        self._evaluate_candidates()

        current_result = await self._run_backtest()
        if not current_result:
            self.logger.warning("No backtest result — skipping reflection")
            return

        self.logger.info(
            "Baseline — trades: %d, PnL: %.2f, win_rate: %.1f%%, sharpe: %.2f",
            current_result.total_trades,
            current_result.total_pnl,
            current_result.win_rate * 100,
            current_result.sharpe_ratio,
        )

        hypothesis = await self._find_best_mutation(current_result)
        if not hypothesis:
            self.logger.info("No parameter improvement found during sweep — skipping mutation")
            return

        rationale = hypothesis.get("rationale", "")[:100]
        self.logger.info(
            "Best Parameter Set found: %s -> %s",
            hypothesis.get("strategy"),
            rationale,
        )

        mutated_result = hypothesis.pop("result")
        improvement = mutated_result.sharpe_ratio - current_result.sharpe_ratio

        cand_id = f"{hypothesis.get('strategy')}_cand_{int(time.time())}"
        candidate = {
            "strategy": hypothesis.get("strategy"),
            "params": hypothesis.get("params"),
            "start_date": datetime.now(UTC).isoformat(),
            "end_date": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "position": 0,
            "avg_price": 0.0,
            "realized_pnl": 0.0,
            "trades": 0,
            "status": "active",
            "backtest_improvement": improvement,
        }
        self._candidates[cand_id] = candidate
        self._save_candidates()

        self.logger.warning(
            "CANDIDATE CREATED for 30-day shadow testing: %s. "
            "baseline_sharpe=%.3f -> proposed_sharpe=%.3f. ",
            cand_id,
            current_result.sharpe_ratio,
            mutated_result.sharpe_ratio,
        )
        self._inject_candidates()
        self._last_baseline_result = current_result

    def _evaluate_candidates(self) -> None:
        now = datetime.now(UTC)
        updated = False
        for cand_id, cand in self._candidates.items():
            if cand.get("status") == "active":
                end_date_str = cand.get("end_date")
                if end_date_str:
                    end_date = datetime.fromisoformat(end_date_str)
                    if now >= end_date:
                        cand["status"] = (
                            "pending_live_approval"
                            if cand.get("realized_pnl", 0) > 0
                            else "rejected"
                        )
                        updated = True
                        self.logger.warning(
                            "Candidate %s finished 30-day evaluation. Final PnL: %.2f. Status: %s",
                            cand_id,
                            cand.get("realized_pnl", 0),
                            cand["status"],
                        )
        if updated:
            self._save_candidates()

    async def _find_best_mutation(self, baseline_result: Any) -> dict[str, Any] | None:
        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(self._strategy_config_path))

        best_strategy = None
        best_params = None
        best_sharpe = baseline_result.sharpe_ratio
        best_result = baseline_result

        # Grid search bounds
        search_spaces = {
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

        import itertools

        for strat_name, strat_cfg in cfg.get("strategies", {}).items():
            if not strat_cfg.get("enabled", True):
                continue

            space = search_spaces.get(strat_name)
            if not space:
                continue

            # Get keys and list of possible values
            keys, values = zip(*space.items())
            # Generate Cartesian product
            for val_combination in itertools.product(*values):
                params = dict(zip(keys, val_combination))

                # Check if these params are different from current config params
                current_params = strat_cfg.get("params", {})
                if all(current_params.get(k) == v for k, v in params.items()):
                    continue

                # Run backtest
                override = {strat_name: {"params": params, "enabled": True}}
                res = await self._run_backtest(strategy_config_override=override)
                if res:
                    # We want to find the parameter set with the highest Sharpe ratio
                    if res.sharpe_ratio > best_sharpe:
                        best_sharpe = res.sharpe_ratio
                        best_strategy = strat_name
                        best_params = params
                        best_result = res

        if best_strategy and best_sharpe > baseline_result.sharpe_ratio * 1.05:
            return {
                "strategy": best_strategy,
                "params": best_params,
                "rationale": f"Grid search parameter optimization: Sharpe improved from {baseline_result.sharpe_ratio:.3f} to {best_sharpe:.3f}",
                "result": best_result,
            }
        return None

    async def _run_backtest(
        self,
        strategy_config_override: dict[str, Any] | None = None,
    ) -> Any:
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
        return generate_synthetic_ticks()

    async def _evaluate_mutation(self, hypothesis: dict[str, Any]) -> Any:
        strategy_name = hypothesis.get("strategy")
        param_changes = hypothesis.get("params", {})
        if not strategy_name or not param_changes:
            return None

        strategy_config_override = {
            strategy_name: {"params": param_changes, "enabled": True},
        }
        return await self._run_backtest(
            strategy_config_override=strategy_config_override,
        )

    def _is_improvement(self, baseline: Any, mutated: Any) -> bool:
        if mutated.total_trades < 3:
            return False
        sharpe_improvement = mutated.sharpe_ratio > baseline.sharpe_ratio * 1.05
        win_rate_improvement = mutated.win_rate > baseline.win_rate * 1.05
        pnl_improvement = mutated.total_pnl > baseline.total_pnl * 1.05
        dd_ok = mutated.max_drawdown <= baseline.max_drawdown * 1.1

        score = sum([sharpe_improvement, win_rate_improvement, pnl_improvement])
        overall = score >= 2 and dd_ok
        self.logger.info(
            "Improvement check: sharpe=%s win_rate=%s pnl=%s dd=%s -> %s",
            sharpe_improvement,
            win_rate_improvement,
            pnl_improvement,
            dd_ok,
            overall,
        )
        return overall

    async def _apply_mutation(
        self,
        hypothesis: dict[str, Any],
        result: Any,
    ) -> None:
        if not settings.reflection_mutation_enabled:
            self.logger.warning(
                "Mutation blocked: TRA_REFLECTION_MUTATION_ENABLED is False. "
                "Mutation will be created as a shadow candidate instead."
            )
            return

        strategy_name = hypothesis.get("strategy")
        param_changes = hypothesis.get("params", {})
        if not strategy_name or not param_changes:
            return

        self.logger.info(
            "Applying mutation: %s params=%s",
            strategy_name,
            param_changes,
        )

        cfg = load_yaml_config(self._strategy_config_path)
        if strategy_name in cfg.get("strategies", {}):
            cfg["strategies"][strategy_name]["params"].update(param_changes)
            save_yaml_config(self._strategy_config_path, cfg)

            logger.info(
                "Mutation applied: strategy=%s params=%s sharpe=%.3f pnl=%.2f",
                strategy_name,
                param_changes,
                result.sharpe_ratio,
                result.total_pnl,
            )

            await self.emit(
                SystemEvent.health(
                    component=self.name,
                    status="mutation_applied",
                    details={
                        "strategy": strategy_name,
                        "params": param_changes,
                        "sharpe": round(result.sharpe_ratio, 3),
                        "win_rate": round(result.win_rate, 3),
                        "pnl": round(result.total_pnl, 2),
                        "total_trades": result.total_trades,
                    },
                )
            )
            self.logger.info("Mutation applied and committed: %s", strategy_name)

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update(
            {
                "fill_buffer_size": len(self._fill_buffer),
                "eval_window": settings.reflection_eval_window,
                "active_candidates": sum(
                    1 for c in self._candidates.values() if c.get("status") == "active"
                ),
                "pending_candidates": sum(
                    1
                    for c in self._candidates.values()
                    if c.get("status") == "pending_live_approval"
                ),
                "baseline_pnl": self._baseline_pnl,
            }
        )
        return base

    async def approve_candidate(self, candidate_id: str) -> bool:
        """Manually approve a shadow candidate and apply its params to live trading."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            self.logger.warning("Candidate %s not found", candidate_id)
            return False

        if cand.get("status") != "pending_live_approval":
            self.logger.warning(
                "Candidate %s is not pending approval (status: %s)",
                candidate_id,
                cand.get("status"),
            )
            return False

        strategy_name = cand.get("strategy")
        param_changes = cand.get("params", {})

        # 1. Backtest validation gating (Phase 2)
        self.logger.info("Running validation backtest for candidate %s...", candidate_id)

        # Baseline backtest
        baseline_res = await self._run_backtest()
        if not baseline_res:
            self.logger.warning("Validation Gating: Baseline backtest failed. Aborting approval.")
            return False

        # Mutated/Candidate backtest
        override = {strategy_name: {"params": param_changes, "enabled": True}}
        mutated_res = await self._run_backtest(strategy_config_override=override)
        if not mutated_res:
            self.logger.warning("Validation Gating: Mutated backtest failed. Aborting approval.")
            return False

        # Check Sharpe ratio improvement
        sharpe_improvement = mutated_res.sharpe_ratio - baseline_res.sharpe_ratio
        req_improvement = getattr(settings, "reflection_backtest_gate_threshold", 0.0)

        self.logger.info(
            "Validation Gate Sharpe ratios: baseline=%.3f, candidate=%.3f, improvement=%.3f (required >= %.3f)",
            baseline_res.sharpe_ratio,
            mutated_res.sharpe_ratio,
            sharpe_improvement,
            req_improvement,
        )

        if sharpe_improvement < req_improvement:
            self.logger.warning(
                "Validation Gate FAILED: candidate improvement %.3f < %.3f. Rejecting candidate.",
                sharpe_improvement,
                req_improvement,
            )
            cand["status"] = "failed_gate"
            self._save_candidates()
            return False

        self.logger.info("Validation Gate PASSED! Approving candidate %s", candidate_id)

        self.logger.info(
            "Approving Candidate %s -> %s params=%s", candidate_id, strategy_name, param_changes
        )

        cfg = load_yaml_config(self._strategy_config_path)
        if strategy_name in cfg.get("strategies", {}):
            cfg["strategies"][strategy_name]["params"].update(param_changes)
            save_yaml_config(self._strategy_config_path, cfg)

            cand["status"] = "approved"
            self._save_candidates()

            await self.emit(
                SystemEvent.health(
                    component=self.name,
                    status="candidate_approved",
                    details={"candidate_id": candidate_id, "strategy": strategy_name},
                )
            )
            return True
        return False

    async def reject_candidate(self, candidate_id: str) -> bool:
        """Reject a pending shadow candidate."""
        cand = self._candidates.get(candidate_id)
        if not cand:
            self.logger.warning("Candidate %s not found", candidate_id)
            return False

        if cand.get("status") != "pending_live_approval":
            self.logger.warning("Candidate %s is not pending approval", candidate_id)
            return False

        cand["status"] = "rejected"
        self._save_candidates()
        self.logger.info("Candidate REJECTED: %s", candidate_id)
        return True

    @staticmethod
    def _result_to_dict(r: Any) -> dict[str, Any]:
        return {
            "total_trades": r.total_trades,
            "total_pnl": r.total_pnl,
            "win_rate": r.win_rate,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown": r.max_drawdown,
            "profit_factor": r.profit_factor,
        }


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
            return self._fallback_hypothesis(current_result)

        prompt = self._build_prompt(current_result, mutation_history or [])
        try:
            return await self._call_gemini(prompt)
        except Exception as e:
            self.logger.warning("Gemini API call failed: %s — using fallback", e)
            return self._fallback_hypothesis(current_result)

    async def _call_gemini(self, prompt: str) -> dict[str, Any] | None:
        import httpx

        url = f"{self.BASE_URL}/gemini-2.0-flash:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 512,
            },
        }
        headers = {"x-goog-api-key": self._api_key}
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(url, json=body, headers=headers)
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
            "Suggest ONE strategy parameter mutation to improve performance.\n"
            "Return JSON only:\n"
            '{"strategy": "strategy_name", "params": {"param1": new_value}, '
            '"rationale": "why this change"}\n'
            "Pick a strategy name from the config above. "
            "Change only 1-2 numeric params slightly (+-10-30%).\n"
            "Do not change enabling/disabling or weight. Only mutate params.\n"
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
            self.logger.warning("Failed to parse Gemini response: %s", text[:200])
            return None

    def _fallback_hypothesis(self, result: Any) -> dict[str, Any] | None:
        if result.total_trades < 5:
            return None
        from src.config.strategy_config import load_strategy_config

        cfg = load_strategy_config(str(STRATEGIES_PATH))
        for name, sc in cfg.get("strategies", {}).items():
            if not sc.get("enabled", True):
                continue
            params = sc.get("params", {})
            mutated = {}
            for k, v in params.items():
                if isinstance(v, (int, float)):
                    mult = 1.1 if result.sharpe_ratio < 0.5 else 0.9
                    mutated[k] = round(v * mult, 1)
            if mutated:
                return {
                    "strategy": name,
                    "params": mutated,
                    "rationale": "fallback heuristic adjustment",
                }
        return None

    @property
    def logger(self):
        return logging.getLogger("reflection.llm")


def load_yaml_config(path: Path) -> dict[str, Any]:
    if path.exists():
        with path.open() as f:
            return yaml.safe_load(f) or {}
    from src.config.strategy_config import DEFAULT_CONFIG

    return dict(DEFAULT_CONFIG)


def save_yaml_config(path: Path, cfg: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
    tmp.rename(path)
    logger.info("Config saved to %s", path)
