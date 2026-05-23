import logging
from dataclasses import dataclass, field
from typing import Any

from src.agents import StrategyGenAgent
from src.agents.execution import ExecutionAgent
from src.agents.risk_mgmt import RiskManagementAgent
from src.event_store.memory import InMemoryEventStore
from src.schemas.events import (
    Event,
    EventType,
    Exchange,
    FillEvent,
    OrderEvent,
    OrderSide,
    TickEvent,
)

logger = logging.getLogger("backtest.engine")


@dataclass
class BacktestResult:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_value: float = 0.0
    final_value: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    @property
    def return_pct(self) -> float:
        if self.peak_value == 0:
            return 0.0
        return ((self.final_value - self.peak_value) / self.peak_value) * 100


class BacktestEngine:
    def __init__(
        self,
        strategies: list[Any] | None = None,
        initial_capital: float = 1_000_000.0,
    ):
        self._event_store = InMemoryEventStore()
        self._strategy_gen = StrategyGenAgent(event_store=self._event_store)
        self._risk_mgmt = RiskManagementAgent(event_store=self._event_store)
        self._execution = ExecutionAgent(event_store=self._event_store)
        self._initial_capital = initial_capital
        self._capital = initial_capital
        self._positions: dict[str, dict[str, Any]] = {}
        self._trade_log: list[dict[str, Any]] = []
        self._equity_curve: list[float] = []

        if strategies:
            for s in strategies:
                self._strategy_gen.register_strategy(s)

    async def run(self, ticks: list[dict[str, Any]]) -> BacktestResult:
        await self._event_store.connect()
        await self._strategy_gen.start()
        await self._risk_mgmt.start()
        await self._execution.start()

        self._capital = self._initial_capital
        self._peak_value = self._initial_capital

        for tick_data in ticks:
            tick = TickEvent.create(
                instrument=tick_data.get("instrument", "TEST"),
                exchange=Exchange(tick_data.get("exchange", "NSE")),
                last_price=tick_data.get("price", 100.0),
                volume=tick_data.get("volume", 1000),
            )
            await self._event_store.append("events.bus", tick)

            events = await self._event_store.read("events.bus", offset=0, limit=100)
            for event in events:
                if event.event_type == EventType.TICK:
                    await self._strategy_gen.on_event(event)
                elif event.event_type == EventType.SIGNAL:
                    await self._risk_mgmt.on_event(event)
                elif event.event_type == EventType.RISK_CHECK:
                    await self._execution.on_event(event)

            orders = await self._event_store.read("events.bus", offset=0, limit=200)
            for event in orders:
                if event.event_type == EventType.ORDER_CREATED:
                    await self._simulate_fill(event)

        await self._strategy_gen.stop()
        await self._risk_mgmt.stop()
        await self._execution.stop()

        return self._compute_results()

    async def _simulate_fill(self, event: Event) -> None:
        order = OrderEvent(**event.model_dump())
        price = order.price or 100.0
        fill = FillEvent.create(
            order_id=order.event_id,
            instrument=order.instrument,
            exchange=order.exchange,
            side=order.side,
            fill_price=price,
            fill_quantity=order.quantity,
        )
        await self._event_store.append("events.bus", fill)
        self._record_trade(order, price)

    def _record_trade(self, order: OrderEvent, fill_price: float) -> None:
        instrument = order.instrument
        quantity = order.quantity
        side = order.side
        cost = fill_price * quantity
        if side == OrderSide.BUY:
            if instrument not in self._positions:
                self._positions[instrument] = {"quantity": 0, "cost": 0.0}
            pos = self._positions[instrument]
            total_cost = pos["cost"] + cost
            total_qty = pos["quantity"] + quantity
            pos["avg_cost"] = total_cost / total_qty if total_qty > 0 else 0
            pos["quantity"] = total_qty
            pos["cost"] = total_cost
            self._capital -= cost
        else:
            pos = self._positions.get(instrument, {"quantity": 0, "avg_cost": 0.0})
            pnl = (fill_price - pos["avg_cost"]) * quantity if pos["quantity"] > 0 else 0.0
            self._capital += cost
            self._capital += pnl
            if instrument in self._positions:
                self._positions[instrument]["quantity"] -= quantity
            self._trade_log.append({
                "instrument": instrument,
                "side": "sell",
                "quantity": quantity,
                "price": fill_price,
                "pnl": pnl,
            })
        exposure = sum(p.get("quantity", 0) * p.get("avg_cost", 0) for p in self._positions.values())
        total = self._capital + exposure
        self._equity_curve.append(total)
        if total > self._peak_value:
            self._peak_value = total

    def _compute_results(self) -> BacktestResult:
        result = BacktestResult()
        result.equity_curve = self._equity_curve
        result.peak_value = self._peak_value
        result.final_value = self._equity_curve[-1] if self._equity_curve else self._initial_capital
        result.total_pnl = result.final_value - self._initial_capital
        result.trades = self._trade_log
        result.total_trades = len(self._trade_log)

        wins = [t for t in self._trade_log if t.get("pnl", 0) > 0]
        losses = [t for t in self._trade_log if t.get("pnl", 0) <= 0]
        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = result.winning_trades / result.total_trades if result.total_trades > 0 else 0.0
        result.avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
        result.avg_loss = abs(sum(t["pnl"] for t in losses)) / len(losses) if losses else 0.0
        result.profit_factor = (
            sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))
            if losses and abs(sum(t["pnl"] for t in losses)) > 0
            else float("inf") if wins else 0.0
        )

        peak = self._initial_capital
        for val in self._equity_curve:
            peak = max(peak, val)
            dd = (peak - val) / peak if peak > 0 else 0
            result.max_drawdown = max(result.max_drawdown, dd)

        returns = []
        for i in range(1, len(self._equity_curve)):
            prev = self._equity_curve[i - 1]
            if prev > 0:
                returns.append((self._equity_curve[i] - prev) / prev)
        if len(returns) > 1:
            avg_r = sum(returns) / len(returns)
            variance = sum((r - avg_r) ** 2 for r in returns) / len(returns)
            std = variance ** 0.5
            result.sharpe_ratio = (avg_r / std) * (252 ** 0.5) if std > 0 else 0.0

        return result
