import logging
import numpy as np
from typing import Any

logger = logging.getLogger("analytics.strategy_decay")

class StrategyDecayDetector:
    """
    Advanced Strategy Decay Detector monitoring:
    - Rolling Sharpe, Sortino, Win Rate, Expectancy, Drawdown
    - Actions: Alert, Disable, Reduce Position Size
    """
    def __init__(self, system=None, rolling_window: int = 30, confidence_level: float = 0.95):
        self.system = system
        self.rolling_window = rolling_window
        self.confidence_level = confidence_level
        self._strategy_trades: dict[str, list[dict[str, float]]] = {}
        # Stores historical baselines for each strategy
        self._baselines: dict[str, dict[str, float]] = {}

    def set_baseline(self, strategy_name: str, sharpe: float, sortino: float, win_rate: float, expectancy: float, max_dd: float):
        self._baselines[strategy_name] = {
            "sharpe": sharpe,
            "sortino": sortino,
            "win_rate": win_rate,
            "expectancy": expectancy,
            "max_dd": max_dd,
        }

    def record_trade(self, strategy_name: str, pnl: float, equity: float) -> None:
        if not strategy_name or strategy_name == "unknown":
            return

        self._strategy_trades.setdefault(strategy_name, []).append({"pnl": pnl, "equity": equity})
        trades = self._strategy_trades[strategy_name]

        if len(trades) >= self.rolling_window:
            self._evaluate_decay(strategy_name, trades[-self.rolling_window:])

    def _evaluate_decay(self, strategy_name: str, window_trades: list[dict[str, float]]) -> None:
        baseline = self._baselines.get(strategy_name)
        if not baseline:
            # Need a baseline to detect decay based on confidence interval
            return
            
        pnls = [t["pnl"] for t in window_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        # Calculate Rolling Metrics
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls)
        downside_std = np.std(losses) if losses else 0.0
        
        rolling_sharpe = (mean_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0
        rolling_sortino = (mean_pnl / downside_std * np.sqrt(252)) if downside_std > 0 else rolling_sharpe
        
        rolling_win_rate = len(wins) / len(pnls)
        
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = abs(np.mean(losses)) if losses else 0.0
        rolling_expectancy = (rolling_win_rate * avg_win) - ((1 - rolling_win_rate) * avg_loss)
        
        equities = [t["equity"] for t in window_trades]
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                
        # Detection Logic: Performance < Historical Confidence Interval
        # For simplicity, we trigger if rolling metric is less than 60% of baseline (representing lower confidence bound)
        # or if drawdown exceeds baseline max drawdown by 1.5x
        decay_factors = []
        if rolling_sharpe < baseline["sharpe"] * 0.6:
            decay_factors.append(f"Sharpe {rolling_sharpe:.2f} < {baseline['sharpe']*.6:.2f}")
        if rolling_sortino < baseline["sortino"] * 0.6:
            decay_factors.append(f"Sortino {rolling_sortino:.2f} < {baseline['sortino']*.6:.2f}")
        if rolling_win_rate < baseline["win_rate"] * 0.7:
            decay_factors.append(f"Win Rate {rolling_win_rate:.2f} < {baseline['win_rate']*.7:.2f}")
        if rolling_expectancy < baseline["expectancy"] * 0.5:
            decay_factors.append(f"Expectancy {rolling_expectancy:.2f} < {baseline['expectancy']*.5:.2f}")
        if max_dd > baseline["max_dd"] * 1.5:
            decay_factors.append(f"Max DD {max_dd:.2%} > {baseline['max_dd']*1.5:.2%}")
            
        if len(decay_factors) >= 2:
            self._take_action(strategy_name, decay_factors)

    def _take_action(self, strategy_name: str, decay_factors: list[str]) -> None:
        reason = ", ".join(decay_factors)
        logger.critical("STRATEGY DECAY DETECTED for %s. Factors: %s", strategy_name, reason)
        
        if self.system and hasattr(self.system, "strategy_gen"):
            sg = self.system.strategy_gen
            if strategy_name in sg._strategy_weights:
                # Reduce position size or disable
                current_weight = sg._strategy_weights[strategy_name]
                new_weight = current_weight * 0.25 # Reduce by 75%
                if new_weight < 0.1:
                    new_weight = 0.0
                    
                sg._strategy_weights[strategy_name] = new_weight
                logger.warning("Decay Detector: Reduced %s weight to %.2f", strategy_name, new_weight)
                
        if self.system and hasattr(self.system, "market_intel") and self.system.market_intel:
            try:
                from src.schemas.events import Event, EventMetadata, EventType
                decay_event = Event(
                    event_type=EventType.SYSTEM_ERROR,
                    stream="system.errors",
                    data={
                        "fatal": False,
                        "reason": f"Strategy decay: {strategy_name}. {reason}"
                    },
                    metadata=EventMetadata(producer="decay_detector")
                )
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.system.market_intel.emit(decay_event), loop)
            except Exception as e:
                logger.error("Failed to emit strategy decay event: %s", e)
