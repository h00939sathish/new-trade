import itertools
import logging
from datetime import UTC, date, datetime
from typing import Any

from src.backtest.engine import BacktestEngine, BacktestResult
from src.config.strategy_config import STRATEGY_REGISTRY

logger = logging.getLogger("backtest.walk_forward")

DEFAULT_PARAMETER_GRIDS = {
    "momentum": {
        "short_window": [3, 5, 8],
        "long_window": [15, 20, 25],
        "threshold": [0.01, 0.02, 0.03],
    },
    "mean_reversion": {
        "window": [10, 15, 20, 25],
        "entry_z": [1.5, 2.0, 2.5],
        "exit_z": [0.0, 0.5, 1.0],
    },
    "rsi": {
        "window": [10, 14, 20],
        "oversold": [25.0, 30.0, 35.0],
        "overbought": [65.0, 70.0, 75.0],
    },
}


class WalkForwardValidator:
    def __init__(
        self,
        train_days: int = 60,
        test_days: int = 20,
        initial_capital: float = 1_000_000.0,
        parameter_grids: dict[str, dict[str, list[Any]]] | None = None,
    ):
        self.train_days = train_days
        self.test_days = test_days
        self.initial_capital = initial_capital
        self.parameter_grids = parameter_grids or DEFAULT_PARAMETER_GRIDS

    def _get_tick_date(self, tick: dict[str, Any]) -> date:
        ts = tick.get("timestamp")
        if not ts:
            return date.min
        if isinstance(ts, str):
            return datetime.fromisoformat(ts).date()
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, UTC).date()
        if isinstance(ts, datetime):
            return ts.date()
        if isinstance(ts, date):
            return ts
        return date.min

    def split_data(self, ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group ticks by date and return sorted unique dates along with mapped ticks."""
        ticks_sorted = sorted(ticks, key=lambda x: x.get("timestamp") or 0)
        dates_map: dict[date, list[dict[str, Any]]] = {}
        for t in ticks_sorted:
            d = self._get_tick_date(t)
            if d != date.min:
                dates_map.setdefault(d, []).append(t)

        sorted_dates = sorted(dates_map.keys())
        return sorted_dates, dates_map

    async def run_validation(
        self,
        strategy_name: str,
        ticks: list[dict[str, Any]],
        metric: str = "sharpe_ratio",
    ) -> dict[str, Any]:
        """Perform rolling walk-forward validation on a single strategy."""
        sorted_dates, dates_map = self.split_data(ticks)
        if len(sorted_dates) < self.train_days + self.test_days:
            raise ValueError(
                f"Insufficient historical dates: {len(sorted_dates)} available, "
                f"need at least {self.train_days + self.test_days} for walk-forward."
            )

        grid = self.parameter_grids.get(strategy_name)
        if not grid:
            raise ValueError(f"No optimization grid defined for strategy: {strategy_name}")

        windows = []
        i = 0
        while i + self.train_days + self.test_days <= len(sorted_dates):
            train_dates = sorted_dates[i : i + self.train_days]
            test_dates = sorted_dates[i + self.train_days : i + self.train_days + self.test_days]

            train_ticks = []
            for d in train_dates:
                train_ticks.extend(dates_map[d])

            test_ticks = []
            for d in test_dates:
                test_ticks.extend(dates_map[d])

            windows.append(
                {
                    "train_range": (train_dates[0], train_dates[-1]),
                    "test_range": (test_dates[0], test_dates[-1]),
                    "train_ticks": train_ticks,
                    "test_ticks": test_ticks,
                }
            )
            # Slide window forward by test_days (non-overlapping out-of-sample periods)
            i += self.test_days

        logger.info("Generated %d walk-forward rolling windows.", len(windows))

        out_of_sample_trades = []
        out_of_sample_equity_curve = []
        current_capital = self.initial_capital
        history = []

        for idx, win in enumerate(windows):
            logger.info(
                "Window %d/%d: Optimizing on %s to %s",
                idx + 1,
                len(windows),
                win["train_range"][0],
                win["train_range"][1],
            )

            # 1. Parameter sweep on training set
            best_params = await self.optimize(strategy_name, win["train_ticks"], grid, metric)
            logger.info("Window %d: Selected best params: %s", idx + 1, best_params)

            # 2. Backtest out-of-sample on test set with optimized parameters
            test_engine = BacktestEngine(initial_capital=current_capital)
            strat_cls = STRATEGY_REGISTRY[strategy_name]
            test_engine._strategy_gen.register_strategy(strat_cls(**best_params))

            result: BacktestResult = await test_engine.run(win["test_ticks"])

            # Record out-of-sample trades
            for t in result.trades:
                out_of_sample_trades.append({**t, "window": idx + 1})

            # Chain equity curves smoothly
            out_of_sample_equity_curve.extend(result.equity_curve)

            prev_capital = current_capital
            current_capital = result.final_value
            pnl = current_capital - prev_capital

            history.append(
                {
                    "window": idx + 1,
                    "train_range": (str(win["train_range"][0]), str(win["train_range"][1])),
                    "test_range": (str(win["test_range"][0]), str(win["test_range"][1])),
                    "best_params": best_params,
                    "test_pnl": pnl,
                    "test_trades_count": len(result.trades),
                    "test_sharpe": result.sharpe_ratio,
                }
            )

        # 3. Aggregate final out-of-sample statistics
        final_result = self._aggregate_results(
            out_of_sample_trades, out_of_sample_equity_curve, self.initial_capital
        )

        return {
            "strategy": strategy_name,
            "metric_optimized": metric,
            "windows": history,
            "overall_oos_performance": final_result,
        }

    async def optimize(
        self,
        strategy_name: str,
        ticks: list[dict[str, Any]],
        grid: dict[str, list[Any]],
        metric: str,
    ) -> dict[str, Any]:
        """Runs a grid search parameter sweep on the ticks dataset and selects the best parameters."""
        keys = list(grid.keys())
        values = list(grid.values())
        combinations = [dict(zip(keys, prod)) for prod in itertools.product(*values)]

        best_score = -float("inf")
        # Initialize default parameters from grid first combo
        best_params = combinations[0] if combinations else {}

        strat_cls = STRATEGY_REGISTRY[strategy_name]

        for combo in combinations:
            engine = BacktestEngine(initial_capital=self.initial_capital)
            engine._strategy_gen.register_strategy(strat_cls(**combo))

            res: BacktestResult = await engine.run(ticks)
            score = getattr(res, metric, 0.0)

            # Safeguard: check trades count to prevent choosing parameter that avoids trading entirely
            if res.total_trades > 0 and score > best_score:
                best_score = score
                best_params = combo

        return best_params

    def _aggregate_results(
        self, trades: list[dict[str, Any]], equity_curve: list[float], initial_capital: float
    ) -> dict[str, Any]:
        """Compute consolidated backtest statistics for out-of-sample performance."""
        total_trades = len(trades)
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]

        winning_trades = len(wins)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        profit_factor = (
            sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))
            if losses and abs(sum(t["pnl"] for t in losses)) > 0
            else float("inf")
            if wins
            else 0.0
        )

        final_value = equity_curve[-1] if equity_curve else initial_capital
        total_pnl = final_value - initial_capital

        max_dd = 0.0
        peak = initial_capital
        for val in equity_curve:
            peak = max(peak, val)
            dd = (peak - val) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        # Compute Sharpe ratio on out-of-sample equity steps
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            if prev > 0:
                returns.append((equity_curve[i] - prev) / prev)

        sharpe = 0.0
        if len(returns) > 1:
            avg_r = sum(returns) / len(returns)
            variance = sum((r - avg_r) ** 2 for r in returns) / len(returns)
            std = variance**0.5
            sharpe = (avg_r / std) * (252**0.5) if std > 0 else 0.0

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "max_drawdown": max_dd,
            "sharpe_ratio": sharpe,
            "final_value": final_value,
        }
