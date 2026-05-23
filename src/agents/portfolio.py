from typing import Any

from src.agents.base import BaseAgent
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

    async def on_start(self) -> None:
        self.logger.info(
            "Portfolio Optimization Agent initializing (capital=%.0f)", self._capital
        )
        self.subscribe(EventType.FILL)
        self.subscribe(EventType.SIGNAL)
        self.subscribe(EventType.PORTFOLIO_UPDATE)

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.FILL:
                await self._on_fill(event)
            case EventType.SIGNAL:
                await self._on_signal(event)
            case EventType.PORTFOLIO_UPDATE:
                self._on_portfolio_update(event)

    async def _on_fill(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        side = event.data.get("side", "buy")
        quantity = event.data.get("fill_quantity", 0)
        price = event.data.get("fill_price", 0.0)

        if instrument not in self._positions:
            self._positions[instrument] = {
                "quantity": 0,
                "avg_cost": 0.0,
                "total_bought": 0,
                "total_sold": 0,
            }
        pos = self._positions[instrument]
        if side == "buy":
            total_cost = pos["avg_cost"] * pos["quantity"] + price * quantity
            pos["quantity"] += quantity
            pos["avg_cost"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else 0
            pos["total_bought"] += quantity
        else:
            pos["quantity"] -= quantity
            pos["total_sold"] += quantity
            realized_pnl = (price - pos["avg_cost"]) * quantity
            self._pnl += realized_pnl
            self._trade_history.append({
                "instrument": instrument,
                "side": "sell",
                "quantity": quantity,
                "price": price,
                "realized_pnl": realized_pnl,
                "avg_cost": pos["avg_cost"],
            })

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
        self._capital = event.data.get("total_value", self._capital)
        if self._capital > self._peak_capital:
            self._peak_capital = self._capital

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

    async def _emit_portfolio_update(self, instrument: str, side: str) -> None:
        total_value = self._capital + self.get_total_exposure()
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
