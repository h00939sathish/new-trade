"""
SSOT: This module's `position_registry` singleton is the single source of truth
for all position state in the system. All writes (fills, SL/TP, trailing stops)
go through this registry. Reads from other modules (e.g., portfolio analytics)
must treat their caches as read-only.

Related: src/agents/portfolio.py contains `portfolio_opt._positions` which is
a read-only cache used for analytics/attribution snapshots. It must NEVER be
written to directly — it is rebuilt from position_registry on demand.
"""

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from src.config.settings import settings

logger = logging.getLogger("risk.position_registry")


class PositionRegistry:
    """Thread-safe, singleton position registry with dual locking for writes.

    Uses both asyncio.Lock (for cooperative async mutual exclusion) and
    threading.RLock (for cross-thread read/write safety). Sync read methods
    (get_position, get_quantity, get_all_positions) only acquire the threading
    lock since they don't yield. Async write methods acquire both to protect
    against concurrent sync reads from other threads.

    Tracks:
    - Net quantity per instrument
    - Average cost/entry price
    - Realized PnL
    - SL/TP levels (set by strategy_gen on entry)
    """

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> "PositionRegistry":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._positions: dict[str, dict[str, Any]] = {}
        self._lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._realized_pnl: dict[str, float] = defaultdict(float)
        self._tax_lot_method: str = settings.risk_tax_lot_method
        self._async_lock: asyncio.Lock | None = None
        # Protects _positions from concurrent sync reads and async writes.
        # Safe because no async write method awaits while holding this lock.
        self._data_lock: threading.RLock = threading.RLock()
        self._initialized = True

    def _get_async_lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def get_position(self, instrument: str) -> dict[str, Any]:
        """Get current position for an instrument."""
        with self._data_lock:
            pos = self._positions.get(
                instrument,
                {
                    "quantity": 0,
                    "avg_price": 0.0,
                    "side": None,
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                    "stop_loss_pct": 0.0,
                    "take_profit_pct": 0.0,
                },
            )
            return {
                **pos,
                "realized_pnl": self._realized_pnl.get(instrument, 0.0),
                "lots": list(self._lots.get(instrument, [])),
            }

    def get_quantity(self, instrument: str) -> int:
        """Get net quantity for an instrument."""
        with self._data_lock:
            return self._positions.get(instrument, {}).get("quantity", 0)

    def get_all_positions(self) -> dict[str, dict[str, Any]]:
        """Get all positions with non-zero quantity."""
        with self._data_lock:
            return {k: v for k, v in self._positions.items() if v.get("quantity", 0) != 0}

    async def update_from_fill(
        self,
        instrument: str,
        side: str,
        fill_qty: int,
        fill_price: float,
        lot_id: str | None = None,
    ) -> dict[str, Any]:
        """Update position from a fill event. Returns the updated position.

        Tax lot accounting respects ``settings.risk_tax_lot_method``:
        - ``average_cost`` (default) — blended avg_price (legacy behaviour).
        - ``fifo`` — cost basis from oldest lots on partial closes.
        - ``specific_id`` — requires ``lot_id`` on sell fills.
        """
        async with self._get_async_lock():
            with self._data_lock:
                if instrument not in self._positions:
                    self._positions[instrument] = {
                        "quantity": 0,
                        "avg_price": 0.0,
                        "side": None,
                        "stop_loss": 0.0,
                        "take_profit": 0.0,
                        "stop_loss_pct": 0.0,
                        "take_profit_pct": 0.0,
                    }

                pos = self._positions[instrument]
                qty_change = fill_qty if side == "buy" else -fill_qty
                old_qty = pos["quantity"]
                new_qty = old_qty + qty_change

                if side == "buy":
                    self._lots[instrument].append({
                        "qty": fill_qty,
                        "price": fill_price,
                        "timestamp": datetime.now(UTC),
                        "lot_id": lot_id or f"{instrument}-{datetime.now(UTC).isoformat()}",
                    })
                else:
                    if self._tax_lot_method == "specific_id" and lot_id is None:
                        raise ValueError(
                            "specific_id tax lot method requires lot_id on sell fills"
                        )
                    remaining = fill_qty
                    consumed_realized = 0.0
                    while remaining > 0 and self._lots[instrument]:
                        if self._tax_lot_method == "specific_id":
                            lot = next(
                                (l for l in self._lots[instrument] if l["lot_id"] == lot_id),
                                None,
                            )
                            if lot is None:
                                raise ValueError(f"Lot {lot_id} not found for {instrument}")
                            debit = min(remaining, lot["qty"])
                            lot["qty"] -= debit
                            consumed_realized += debit * (fill_price - lot["price"])
                            if lot["qty"] == 0:
                                self._lots[instrument].remove(lot)
                            remaining -= debit
                        else:
                            lot = self._lots[instrument][0]
                            debit = min(remaining, lot["qty"])
                            lot["qty"] -= debit
                            consumed_realized += debit * (fill_price - lot["price"])
                            if lot["qty"] == 0:
                                self._lots[instrument].pop(0)
                            remaining -= debit
                    self._realized_pnl[instrument] += consumed_realized

                if new_qty == 0:
                    self._positions[instrument] = {
                        "quantity": 0,
                        "avg_price": 0.0,
                        "side": None,
                        "stop_loss": 0.0,
                        "take_profit": 0.0,
                        "stop_loss_pct": 0.0,
                        "take_profit_pct": 0.0,
                    }
                    self._lots.pop(instrument, None)
                    logger.info("Position closed: %s", instrument)
                else:
                    current_side = "long" if new_qty > 0 else "short"
                    if self._tax_lot_method == "average_cost":
                        if (
                            old_qty == 0
                            or (old_qty > 0 and qty_change > 0)
                            or (old_qty < 0 and qty_change < 0)
                        ):
                            total_cost = (pos["avg_price"] * abs(old_qty)) + (fill_price * fill_qty)
                            pos["avg_price"] = total_cost / abs(new_qty) if new_qty != 0 else 0.0
                    else:
                        lots = self._lots[instrument]
                        if lots:
                            total_cost = sum(l["qty"] * l["price"] for l in lots)
                            total_qty = sum(l["qty"] for l in lots)
                            pos["avg_price"] = total_cost / total_qty if total_qty else 0.0

                    pos["quantity"] = new_qty
                    pos["side"] = current_side
                    logger.info(
                        "Position updated: %s qty=%d avg=%.2f side=%s",
                        instrument,
                        new_qty,
                        pos["avg_price"],
                        current_side,
                    )

                return self._positions[instrument]

    async def set_sl_tp(
        self,
        instrument: str,
        stop_loss: float,
        take_profit: float,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
    ) -> None:
        """Set SL/TP levels for a position (called by strategy_gen after fill)."""
        async with self._get_async_lock():
            with self._data_lock:
                if instrument in self._positions:
                    self._positions[instrument].update(
                        {
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "stop_loss_pct": stop_loss_pct,
                            "take_profit_pct": take_profit_pct,
                        }
                    )

    async def update_trailing_sl(self, instrument: str, new_sl: float) -> None:
        """Update trailing stop-loss if the new level is tighter."""
        async with self._get_async_lock():
            with self._data_lock:
                if instrument in self._positions:
                    pos = self._positions[instrument]
                    if pos["side"] == "long" and new_sl > pos["stop_loss"]:
                        pos["stop_loss"] = new_sl
                    elif pos["side"] == "short" and (
                        new_sl < pos["stop_loss"] or pos["stop_loss"] == 0.0
                    ):
                        pos["stop_loss"] = new_sl

    async def sync_from_portfolio(self, portfolio_positions: dict[str, dict[str, Any]]) -> None:
        """Synchronize positions from the PortfolioAgent's internal state."""
        async with self._get_async_lock():
            with self._data_lock:
                self._positions.clear()
                for instrument, data in portfolio_positions.items():
                    if data.get("quantity", 0) != 0:
                        self._positions[instrument] = {
                            "quantity": data["quantity"],
                            "avg_price": data.get("avg_cost", 0.0),
                            "side": "long" if data["quantity"] > 0 else "short",
                            "stop_loss": 0.0,
                            "take_profit": 0.0,
                            "stop_loss_pct": 0.0,
                            "take_profit_pct": 0.0,
                        }

    def get_overnight_snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a deep copy of all positions for EOD snapshots (gap-risk monitoring)."""
        with self._data_lock:
            import copy

            return {k: copy.deepcopy(v) for k, v in self._positions.items() if v.get("quantity", 0) != 0}

    def reset(self) -> None:
        """Clear all positions (used in testing)."""
        with self._data_lock:
            self._positions.clear()
            self._lots.clear()
            self._realized_pnl.clear()

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset the singleton instance (used in testing)."""
        with cls._singleton_lock:
            cls._instance = None


# Module-level singleton access
position_registry = PositionRegistry()
