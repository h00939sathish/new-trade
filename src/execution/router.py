"""DEPRECATED: This module is not used by the trading system.

The ExecutionAgent in src/agents/execution.py handles all order routing
directly, including paper/live mode switching. This module contains
TradingRouter, PaperBroker, and LiveOrderGuard which are never imported.

Scheduled for removal in a future version.
"""
from __future__ import annotations

import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from src.schemas.events import Exchange, OrderSide, OrderType, ProductType

warnings.warn(
    "src.execution.router is deprecated and unused. Use src.agents.execution instead.",
    DeprecationWarning,
    stacklevel=2,
)

ExecutionMode = Literal["paper", "live"]


@dataclass(frozen=True)
class OrderCommand:
    instrument: str
    exchange: Exchange
    side: OrderSide
    order_type: OrderType
    quantity: int
    product: ProductType
    price: float | None = None
    trigger_price: float | None = None
    variety: str = "regular"
    tag: str | None = None


@dataclass(frozen=True)
class OrderResult:
    accepted: bool
    mode: ExecutionMode
    status: Literal["accepted", "filled", "rejected"]
    order_id: str
    broker_order_id: str | None = None
    fill_price: float | None = None
    fill_quantity: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveOrderGuard:
    allow_live_orders: bool = False
    acknowledgement: str = ""

    def approve(self, acknowledgement: str | None) -> bool:
        return (
            self.allow_live_orders
            and bool(self.acknowledgement)
            and acknowledgement == self.acknowledgement
        )


class LiveBroker(Protocol):
    async def place_order(self, command: OrderCommand) -> str: ...


class PaperBroker:
    def __init__(self, initial_cash: float = 1_000_000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, int] = {}
        self.orders: list[OrderCommand] = []

    async def place_order(self, command: OrderCommand) -> OrderResult:
        order_id = f"PAPER-{uuid.uuid4().hex[:12]}"
        fill_price = command.price or 0.0
        notional = fill_price * command.quantity

        if command.side == OrderSide.BUY and notional > self.cash:
            return OrderResult(
                accepted=False,
                mode="paper",
                status="rejected",
                order_id=order_id,
                error="insufficient_cash",
            )

        self.orders.append(command)
        signed_quantity = command.quantity if command.side == OrderSide.BUY else -command.quantity
        current_quantity = self.positions.get(command.instrument, 0)
        self.positions[command.instrument] = current_quantity + signed_quantity
        self.cash -= notional if command.side == OrderSide.BUY else -notional

        return OrderResult(
            accepted=True,
            mode="paper",
            status="filled",
            order_id=order_id,
            broker_order_id=order_id,
            fill_price=fill_price,
            fill_quantity=command.quantity,
        )


class TradingRouter:
    def __init__(
        self,
        paper_broker: PaperBroker,
        live_broker: LiveBroker | None = None,
        live_guard: LiveOrderGuard | None = None,
    ):
        self.paper_broker = paper_broker
        self.live_broker = live_broker
        self.live_guard = live_guard or LiveOrderGuard()

    async def place_order(
        self,
        command: OrderCommand,
        mode: ExecutionMode = "paper",
        acknowledgement: str | None = None,
    ) -> OrderResult:
        if mode == "paper":
            return await self.paper_broker.place_order(command)

        if not self.live_guard.approve(acknowledgement):
            return OrderResult(
                accepted=False,
                mode="live",
                status="rejected",
                order_id=f"REJECTED-{uuid.uuid4().hex[:12]}",
                error="live_orders_disabled",
            )
        if self.live_broker is None:
            return OrderResult(
                accepted=False,
                mode="live",
                status="rejected",
                order_id=f"REJECTED-{uuid.uuid4().hex[:12]}",
                error="live_broker_unavailable",
            )

        broker_order_id = await self.live_broker.place_order(command)
        return OrderResult(
            accepted=True,
            mode="live",
            status="accepted",
            order_id=broker_order_id,
            broker_order_id=broker_order_id,
        )
