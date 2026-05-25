import logging
import numpy as np
from typing import Any

logger = logging.getLogger("monitoring.decay_detector")

class PerformanceDecayDetector:
    def __init__(self, system=None, rolling_window: int = 20, min_trades: int = 15, min_sharpe: float = 0.5):
        self.system = system
        self.rolling_window = rolling_window
        self.min_trades = min_trades
        self.min_sharpe = min_sharpe
        self._strategy_pnls: dict[str, list[float]] = {}

    def record_trade(self, strategy_name: str, pnl: float) -> None:
        if not strategy_name or strategy_name == "unknown":
            return
            
        self._strategy_pnls.setdefault(strategy_name, []).append(pnl)
        pnls = self._strategy_pnls[strategy_name]
        
        logger.info("Decay Detector: Recorded trade for %s, PnL: %.2f. Total trades: %d", strategy_name, pnl, len(pnls))

        if len(pnls) >= self.min_trades:
            # Calculate rolling Sharpe ratio on the trade PnLs
            # (mean trade PnL / std dev of trade PnL) * sqrt(252) as approximation
            window_pnls = pnls[-self.rolling_window:]
            mean_pnl = np.mean(window_pnls)
            std_pnl = np.std(window_pnls)
            
            rolling_sharpe = (mean_pnl / std_pnl) * np.sqrt(252) if std_pnl > 0.0 else 0.0
            
            logger.info("Decay Detector: Strategy %s rolling Sharpe: %.3f", strategy_name, rolling_sharpe)
            
            if rolling_sharpe < self.min_sharpe:
                self._disable_strategy(strategy_name, rolling_sharpe)

    def _disable_strategy(self, strategy_name: str, current_sharpe: float) -> None:
        logger.critical(
            "DECAY DETECTED: Strategy %s has degraded rolling Sharpe: %.3f < %.3f. Disabling strategy.",
            strategy_name, current_sharpe, self.min_sharpe
        )
        if self.system:
            # 1. Zero weight in strategy generator
            if hasattr(self.system, "strategy_gen"):
                sg = self.system.strategy_gen
                if strategy_name in sg._strategy_weights:
                    sg._strategy_weights[strategy_name] = 0.0
                    logger.warning("Decay Detector: Set %s weight to 0.0 in strategy_gen", strategy_name)
                    
            # 2. Emit alert / system event
            try:
                from src.schemas.events import Event, EventType, EventMetadata
                decay_event = Event(
                    event_type=EventType.SYSTEM_ERROR,
                    stream="system.errors",
                    data={
                        "fatal": False,
                        "reason": f"Strategy decay detected: {strategy_name} Sharpe={current_sharpe:.3f} < {self.min_sharpe:.3f}"
                    },
                    metadata=EventMetadata(producer="decay_detector")
                )
                asyncio = __import__("asyncio")
                if hasattr(self.system, "market_intel") and self.system.market_intel:
                    # Emit to event bus
                    asyncio.create_task(self.system.market_intel.emit(decay_event))
            except Exception as e:
                logger.error("Failed to emit strategy decay event: %s", e)
