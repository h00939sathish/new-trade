import asyncio
import time
from collections import deque
from typing import Any

import numpy as np

from src.agents.base import BaseAgent
from src.risk.portfolio_optimizer import InstitutionalPortfolioOptimizer
from src.schemas.events import (
    Event,
    EventType,
    PortfolioEvent,
)


class PortfolioOptimizationAgent(BaseAgent):
    def __init__(self, event_store=None, initial_capital: float = 1_000_000.0):
        super().__init__("portfolio_opt", event_store=event_store)
        self._capital = initial_capital
        self._peak_capital = initial_capital
        self._positions: dict[str, dict[str, Any]] = {}
        self._pnl: float = 0.0
        self._trade_history: list[dict[str, Any]] = []
        self._kelly_fractions: dict[str, float] = {}
        self._price_history: dict[str, deque[float]] = {}
        self._optimal_weights: dict[str, float] = {}
        self._strategy_weights: dict[str, float] = {}
        self._strategy_returns: dict[str, deque[float]] = {}
        self._last_optimization = 0.0
        self._optimizer: InstitutionalPortfolioOptimizer | None = None

    async def on_start(self) -> None:
        self.logger.info(
            "Portfolio Optimization Agent initializing (capital=%.0f)", self._capital
        )
        self.subscribe(EventType.FILL)
        self.subscribe(EventType.SIGNAL)
        self.subscribe(EventType.PORTFOLIO_UPDATE)
        self.subscribe(EventType.TICK)

        from src.monitoring.decay_detector import PerformanceDecayDetector
        self.decay_detector = PerformanceDecayDetector(system=getattr(self, "system", None))

        # Initialise the institutional optimizer from settings
        from src.config.settings import settings
        self._optimizer = InstitutionalPortfolioOptimizer(
            regime=getattr(settings, "portfolio_optimizer_regime", "risk_parity"),
            min_weight=getattr(settings, "portfolio_optimizer_min_weight", 0.05),
            max_weight=getattr(settings, "portfolio_optimizer_max_weight", 0.40),
        )
        self._rebalance_interval = getattr(settings, "portfolio_optimizer_rebalance_interval", 300)

        task = asyncio.create_task(self._reconciliation_loop(), name="portfolio_opt.reconciliation")
        self._tasks.append(task)

    async def _reconciliation_loop(self) -> None:
        await asyncio.sleep(5.0)
        from src.risk.reconciliation import reconcile_positions
        while self._running:
            try:
                system_ref = getattr(self, "system", None)
                if system_ref:
                    await reconcile_positions(system_ref)
            except Exception as e:
                self.logger.error("Reconciliation loop error: %s", e, exc_info=True)
            await asyncio.sleep(300.0)

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.FILL:
                await self._on_fill(event)
            case EventType.SIGNAL:
                await self._on_signal(event)
            case EventType.PORTFOLIO_UPDATE:
                self._on_portfolio_update(event)
            case EventType.TICK:
                await self._on_tick(event)

    async def _on_fill(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        side = event.data.get("side", "buy")
        quantity = event.data.get("fill_quantity", 0)
        price = event.data.get("fill_price", 0.0)
        cost = price * quantity

        if instrument not in self._positions:
            self._positions[instrument] = {
                "quantity": 0,
                "avg_cost": 0.0,
                "total_bought": 0,
                "total_sold": 0,
            }
        pos = self._positions[instrument]
        from src.risk.costs import TransactionCostModel
        cost_model = TransactionCostModel()
        product = event.data.get("product", "mis")
        txn_fee = cost_model.total_cost(side, quantity, price, product=product)

        if side == "buy":
            total_cost = pos["avg_cost"] * pos["quantity"] + cost
            pos["quantity"] += quantity
            pos["avg_cost"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else 0.0
            pos["total_bought"] += quantity
            self._capital -= (cost + txn_fee)  # Deduct cash and entry fees (Bug 2.2 + 3.1)
        else:
            pos["quantity"] -= quantity
            pos["total_sold"] += quantity
            realized_pnl = (price - pos["avg_cost"]) * quantity
            self._pnl += realized_pnl
            self._capital += (cost - txn_fee)  # Credit cash and deduct exit fees (Bug 2.2 + 3.1)
            if pos["quantity"] == 0:
                pos["avg_cost"] = 0.0  # Clear position cost when quantity is 0
            self._trade_history.append({
                "instrument": instrument,
                "side": "sell",
                "quantity": quantity,
                "price": price,
                "realized_pnl": realized_pnl,
                "avg_cost": pos["avg_cost"],
            })

            strategy_name = "unknown"
            system_ref = getattr(self, "system", None)
            if system_ref and hasattr(system_ref, "execution"):
                order_id = event.data.get("order_id", "")
                strategy_name = system_ref.execution._order_strategies.get(order_id, "unknown")

            # Track per-strategy returns for the institutional optimizer
            if strategy_name != "unknown":
                if strategy_name not in self._strategy_returns:
                    self._strategy_returns[strategy_name] = deque(maxlen=500)
                # Store return as fraction of allocated capital for that strategy
                alloc = self._capital * self._strategy_weights.get(strategy_name, 1.0 / max(1, len(self._strategy_returns)))
                ret_frac = realized_pnl / alloc if alloc > 0 else 0.0
                self._strategy_returns[strategy_name].append(ret_frac)

            if hasattr(self, "decay_detector"):
                self.decay_detector.record_trade(strategy_name, realized_pnl)

        self.logger.info(
            "Position %s: qty=%d avg_cost=%.2f",
            instrument, pos["quantity"], pos["avg_cost"],
        )
        await self._emit_portfolio_update(instrument, side)

    async def _on_signal(self, event: Event) -> None:
        signal = event.data
        instrument = signal.get("instrument", "")
        direction = signal.get("direction", "neutral")
        confidence = signal.get("confidence", 0.0)
        kelly = self._kelly_fraction(confidence, direction)
        self._kelly_fractions[instrument] = kelly
        self.logger.debug(
            "Kelly fraction for %s %s: %.2f%%",
            instrument, direction, kelly * 100,
        )

    def _on_portfolio_update(self, event: Event) -> None:
        self._capital = event.data.get("cash", self._capital)
        total_value = event.data.get("total_value", self._capital + self.get_total_exposure())
        if total_value > self._peak_capital:
            self._peak_capital = total_value

    def get_position(self, instrument: str) -> dict[str, Any]:
        return self._positions.get(instrument, {"quantity": 0, "avg_cost": 0.0})

    def get_total_exposure(self) -> float:
        return sum(p["quantity"] * p["avg_cost"] for p in self._positions.values())

    def _kelly_fraction(self, confidence: float, direction: str) -> float:
        if confidence <= 0.5:
            return 0.0
        win_prob = confidence
        loss_prob = 1.0 - confidence
        if loss_prob <= 0:
            return 0.25
        b = 1.0
        kelly = (b * win_prob - loss_prob) / b
        return max(0.0, min(kelly * 0.25, 0.25))

    async def _on_tick(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        price = event.data.get("last_price")
        if price is None:
            return

        if instrument not in self._price_history:
            self._price_history[instrument] = deque(maxlen=500)
        self._price_history[instrument].append(float(price))

        # Run institutional optimizer periodically
        now = time.monotonic()
        if now - self._last_optimization > self._rebalance_interval:
            await self._optimize_portfolio()
            self._last_optimization = now

    async def _optimize_portfolio(self) -> None:
        """Run the institutional optimizer across strategy return series."""
        if self._optimizer is None:
            return

        # --- Strategy-level optimisation (primary) ---
        strategy_data: dict[str, np.ndarray] = {}
        for name, returns_deque in self._strategy_returns.items():
            if len(returns_deque) >= 2:
                strategy_data[name] = np.array(returns_deque)

        if len(strategy_data) >= 2:
            result = self._optimizer.optimize(strategy_data)
            self._strategy_weights = dict(result.weights)
            self.logger.info(
                "Strategy weights [%s]: %s (SR=%.2f, vol=%.4f)",
                result.regime_used,
                {k: f"{v:.1%}" for k, v in result.weights.items()},
                result.sharpe,
                result.expected_vol,
            )
            # Emit rebalance event with enriched payload
            await self.emit(Event(
                event_type=EventType.PORTFOLIO_REBALANCE,
                stream="portfolio.rebalance",
                data={
                    "weights": result.weights,
                    "regime_used": result.regime_used,
                    "expected_return": result.expected_return,
                    "expected_vol": result.expected_vol,
                    "sharpe": result.sharpe,
                    "cov_condition_number": result.cov_condition_number,
                    "shrinkage_intensity": result.shrinkage_intensity,
                    "converged": result.converged,
                },
                metadata={"producer": self.name},
            ))
            return

        # --- Instrument-level fallback (if not enough strategy data yet) ---
        instruments = [k for k, v in self._price_history.items() if len(v) >= 100]
        if len(instruments) < 2:
            return

        returns_dict: dict[str, np.ndarray] = {}
        min_len = min(len(self._price_history[inst]) for inst in instruments)
        for inst in instruments:
            prices = np.array(self._price_history[inst])[-min_len:]
            rets = np.diff(prices) / prices[:-1]
            returns_dict[inst] = rets

        result = self._optimizer.optimize(returns_dict)
        self._optimal_weights = dict(result.weights)
        self.logger.info(
            "Instrument weights (fallback) [%s]: %s",
            result.regime_used,
            {k: f"{v:.1%}" for k, v in result.weights.items()},
        )
        await self.emit(Event(
            event_type=EventType.PORTFOLIO_REBALANCE,
            stream="portfolio.rebalance",
            data={
                "weights": result.weights,
                "regime_used": result.regime_used,
                "expected_return": result.expected_return,
                "expected_vol": result.expected_vol,
                "sharpe": result.sharpe,
                "converged": result.converged,
                "level": "instrument_fallback",
            },
            metadata={"producer": self.name},
        ))

    def get_strategy_weights(self) -> dict[str, float]:
        """Return the current optimal strategy weights for capital allocation."""
        return dict(self._strategy_weights)

    async def _emit_portfolio_update(self, instrument: str, side: str) -> None:
        total_value = self._capital + self.get_total_exposure()
        if total_value > self._peak_capital:
            self._peak_capital = total_value

        # Check KillSwitch limits before emitting
        from src.config.settings import settings
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        ks.setup(
            daily_loss_pct=getattr(settings, "kill_switch_daily_loss_pct", 0.01),
            max_drawdown_pct=getattr(settings, "kill_switch_max_drawdown_pct", 0.05),
            initial_capital=self._peak_capital
        )
        system_ref = getattr(self, "system", None)
        await ks.check_limits(
            current_capital=total_value,
            current_pnl=self._pnl,
            peak_capital=self._peak_capital,
            system=system_ref
        )

        event = PortfolioEvent.create(
            total_value=total_value,
            cash=self._capital,
            pnl=self._pnl,
            exposure=self.get_total_exposure(),
            positions=[
                {"instrument": k, **v}
                for k, v in self._positions.items()
            ],
            producer=self.name,
        )
        await self.emit(event)

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "capital": self._capital,
            "peak_capital": self._peak_capital,
            "pnl": self._pnl,
            "open_positions": len([p for p in self._positions.values() if p["quantity"] != 0]),
            "total_exposure": self.get_total_exposure(),
        })
        return base

    async def on_stop(self) -> None:
        self.logger.info(
            "Portfolio Agent stopping. P&L: %.2f, Capital: %.2f",
            self._pnl, self._capital,
        )
