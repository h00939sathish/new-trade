import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.walk_forward import WalkForwardValidator
from src.config.strategy_config import STRATEGY_REGISTRY
from src.validation.monte_carlo import MonteCarloResult, MonteCarloValidator

logger = logging.getLogger("validation.orchestrator")

REPORTS_DIR = Path("reports/validation")


class ValidationStage(StrEnum):
    BACKTEST = "backtest"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"
    PAPER_TRADE = "paper_trade"


MIN_SHARPE = 1.2
MIN_PROFIT_FACTOR = 1.3
MAX_DRAWDOWN = 0.10
MIN_EXPECTANCY = 0.0


@dataclass
class StageResult:
    stage: ValidationStage
    passed: bool
    metrics: dict[str, Any]
    reason: str = ""


@dataclass
class ValidationReport:
    strategy_name: str
    params: dict[str, Any]
    stages: list[StageResult] = field(default_factory=list)
    passed: bool = False
    overall_score: float = 0.0
    report_path: str = ""


class ValidationPipeline:
    def __init__(self, config_path: str | None = None, data_provider: Any = None):
        self._config_path = config_path
        self._data_provider = data_provider
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        strategy_name: str,
        strategy_class: type | None = None,
        params: dict[str, Any] | None = None,
    ) -> ValidationReport:
        report = ValidationReport(strategy_name=strategy_name, params=params or {})

        backtest_result, trade_pnls = await self._stage_backtest(strategy_name, params)
        if backtest_result:
            stage = self._check_auto_reject(backtest_result)
            report.stages.append(stage)
            if not stage.passed:
                report.passed = False
                report.overall_score = 0.0
                return self._finalize(report)

        ticks = await self._get_ticks()

        wf_stage = await self._stage_walk_forward(strategy_name, params, ticks or [])
        report.stages.append(wf_stage)
        if not wf_stage.passed:
            report.passed = False
            report.overall_score = self._compute_score(report)
            return self._finalize(report)

        mc_stage = self._stage_monte_carlo(backtest_result, trade_pnls or [])
        report.stages.append(mc_stage)

        pt_stage = await self._stage_paper_trade(strategy_name, params)
        report.stages.append(pt_stage)

        report.passed = all(s.passed for s in report.stages)
        report.overall_score = self._compute_score(report)
        return self._finalize(report)

    async def _stage_backtest(
        self, strategy_name: str, params: dict[str, Any] | None
    ) -> tuple[BacktestResult | None, list[float]]:
        try:
            engine = BacktestEngine()
            if strategy_name in STRATEGY_REGISTRY:
                strat_cls = STRATEGY_REGISTRY[strategy_name]
                engine._strategy_gen.register_strategy(strat_cls(**(params or {})))

            ticks = await self._get_ticks()
            if not ticks:
                return None, []

            result = await engine.run(ticks)
            trade_pnls = [t.get("pnl", 0.0) for t in result.trades]
            return result, trade_pnls
        except Exception as e:
            logger.error("Backtest stage failed: %s", e)
            return None, []

    def _check_auto_reject(self, result: BacktestResult) -> StageResult:
        metrics = {
            "total_trades": result.total_trades,
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "profit_factor": round(result.profit_factor, 4),
            "max_drawdown": round(result.max_drawdown, 4),
            "win_rate": round(result.win_rate, 4),
            "total_pnl": round(result.total_pnl, 2),
        }

        reasons = []
        if result.sharpe_ratio < MIN_SHARPE:
            reasons.append(f"Sharpe {result.sharpe_ratio:.2f} < {MIN_SHARPE}")
        if result.profit_factor < MIN_PROFIT_FACTOR:
            reasons.append(f"Profit Factor {result.profit_factor:.2f} < {MIN_PROFIT_FACTOR}")
        if result.max_drawdown > MAX_DRAWDOWN:
            reasons.append(f"Drawdown {result.max_drawdown:.2%} > {MAX_DRAWDOWN:.0%}")
        expectancy = result.total_pnl / result.total_trades if result.total_trades > 0 else 0.0
        if expectancy <= MIN_EXPECTANCY:
            reasons.append(f"Expectancy {expectancy:.2f} <= {MIN_EXPECTANCY}")

        if reasons:
            return StageResult(
                stage=ValidationStage.BACKTEST,
                passed=False,
                metrics=metrics,
                reason="; ".join(reasons),
            )

        return StageResult(
            stage=ValidationStage.BACKTEST,
            passed=True,
            metrics=metrics,
            reason="All backtest gates passed",
        )

    async def _stage_walk_forward(
        self, strategy_name: str, params: dict[str, Any] | None, ticks: list[dict[str, Any]]
    ) -> StageResult:
        try:
            validator = WalkForwardValidator()
            result = await validator.run_validation(strategy_name, ticks)
            oos = result.get("overall_oos_performance", {})

            metrics = {
                "oos_sharpe": round(oos.get("sharpe_ratio", 0.0), 4),
                "oos_profit_factor": round(oos.get("profit_factor", 0.0), 4),
                "oos_max_drawdown": round(oos.get("max_drawdown", 0.0), 4),
                "oos_total_trades": oos.get("total_trades", 0),
                "windows_count": len(result.get("windows", [])),
            }

            oos_sharpe = oos.get("sharpe_ratio", 0.0)
            if oos_sharpe >= MIN_SHARPE * 0.8:
                return StageResult(
                    stage=ValidationStage.WALK_FORWARD,
                    passed=True,
                    metrics=metrics,
                    reason=f"Walk-forward OOS Sharpe {oos_sharpe:.2f}",
                )

            return StageResult(
                stage=ValidationStage.WALK_FORWARD,
                passed=False,
                metrics=metrics,
                reason=f"OOS Sharpe {oos_sharpe:.2f} below threshold",
            )
        except Exception as e:
            logger.error("Walk-forward stage failed: %s", e)
            return StageResult(
                stage=ValidationStage.WALK_FORWARD,
                passed=False,
                metrics={},
                reason=f"Walk-forward error: {e}",
            )

    def _stage_monte_carlo(
        self, result: BacktestResult | None, trade_pnls: list[float]
    ) -> StageResult:
        try:
            if not result or not trade_pnls:
                return StageResult(
                    stage=ValidationStage.MONTE_CARLO,
                    passed=False,
                    metrics={},
                    reason="No trade data for Monte Carlo simulation",
                )

            validator = MonteCarloValidator()
            mc_result: MonteCarloResult = validator.run(result, trade_pnls)

            metrics = {
                "median_sharpe": round(mc_result.median_sharpe, 4),
                "sharpe_ci_lower": round(mc_result.sharpe_ci_lower, 4),
                "sharpe_ci_upper": round(mc_result.sharpe_ci_upper, 4),
                "probability_of_loss": round(mc_result.probability_of_loss, 4),
                "var_95": round(mc_result.var_95, 4),
                "avg_max_drawdown": round(mc_result.avg_max_drawdown, 4),
                "n_simulations": mc_result.n_simulations,
            }

            return StageResult(
                stage=ValidationStage.MONTE_CARLO,
                passed=mc_result.passed,
                metrics=metrics,
                reason="Monte Carlo passed" if mc_result.passed else "Monte Carlo failed",
            )
        except Exception as e:
            logger.error("Monte Carlo stage failed: %s", e)
            return StageResult(
                stage=ValidationStage.MONTE_CARLO,
                passed=False,
                metrics={},
                reason=f"Monte Carlo error: {e}",
            )

    async def _stage_paper_trade(
        self, strategy_name: str, params: dict[str, Any] | None
    ) -> StageResult:
        return StageResult(
            stage=ValidationStage.PAPER_TRADE,
            passed=True,
            metrics={"status": "pending"},
            reason="Paper trade stage: manual approval required",
        )

    def _compute_score(self, report: ValidationReport) -> float:
        if not report.stages:
            return 0.0
        passed_stages = sum(1 for s in report.stages if s.passed)
        return passed_stages / len(report.stages)

    def _finalize(self, report: ValidationReport) -> ValidationReport:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        safe_name = report.strategy_name.replace(" ", "_").lower()
        path = REPORTS_DIR / f"{safe_name}_{timestamp}.json"
        data = {
            "strategy_name": report.strategy_name,
            "params": report.params,
            "passed": report.passed,
            "overall_score": report.overall_score,
            "stages": [
                {
                    "stage": s.stage.value,
                    "passed": s.passed,
                    "metrics": s.metrics,
                    "reason": s.reason,
                }
                for s in report.stages
            ],
            "timestamp": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(data, indent=2))
        report.report_path = str(path)
        logger.info("Validation report written to %s", path)
        return report

    async def _get_ticks(self) -> list[dict[str, Any]] | None:
        provider = self._data_provider
        if provider and hasattr(provider, "get_backtest_ticks"):
            return await provider.get_backtest_ticks()
        from src.connectors.backtest_provider import generate_synthetic_ticks

        return generate_synthetic_ticks()
