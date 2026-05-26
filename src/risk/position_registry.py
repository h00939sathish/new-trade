"""Centralized position registry — single source of truth for all position state.

All agents should read positions from this registry rather than maintaining
separate position trackers. Only PortfolioOptimizationAgent should write to it
(via FILL event processing).

This eliminates the divergence bug where strategy_gen, execution, and portfolio
each maintained separate position state that could fall out of sync.
"""

import logging
import threading
from typing import Any

logger = logging.getLogger("risk.position_registry")


class PositionRegistry:
    """Thread-safe, singleton position registry.

    Tracks:
    - Net quantity per instrument
    - Average cost/entry price
    - Realized PnL
    - SL/TP levels (set by strategy_gen on entry)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls) -> "PositionRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._positions: dict[str, dict[str, Any]] = {}
        self._initialized = True

    def get_position(self, instrument: str) -> dict[str, Any]:
        """Get current position for an instrument."""
        return self._positions.get(instrument, {
            "quantity": 0,
            "avg_price": 0.0,
            "side": None,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "stop_loss_pct": 0.0,
            "take_profit_pct": 0.0,
        })

    def get_quantity(self, instrument: str) -> int:
        """Get net quantity for an instrument."""
        return self._positions.get(instrument, {}).get("quantity", 0)

    def get_all_positions(self) -> dict[str, dict[str, Any]]:
        """Get all positions with non-zero quantity."""
        return {k: v for k, v in self._positions.items() if v.get("quantity", 0) != 0}

    def update_from_fill(
        self,
        instrument: str,
        side: str,
        fill_qty: int,
        fill_price: float,
    ) -> dict[str, Any]:
        """Update position from a fill event. Returns the updated position."""
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

        if new_qty == 0:
            # Position closed
            self._positions[instrument] = {
                "quantity": 0,
                "avg_price": 0.0,
                "side": None,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "stop_loss_pct": 0.0,
                "take_profit_pct": 0.0,
            }
            logger.info("Position closed: %s", instrument)
        else:
            current_side = "long" if new_qty > 0 else "short"
            # Update average price only when adding to position (not reducing)
            if old_qty == 0 or (old_qty > 0 and qty_change > 0) or (old_qty < 0 and qty_change < 0):
                total_cost = (pos["avg_price"] * abs(old_qty)) + (fill_price * fill_qty)
                pos["avg_price"] = total_cost / abs(new_qty) if new_qty != 0 else 0.0

            pos["quantity"] = new_qty
            pos["side"] = current_side
            logger.info(
                "Position updated: %s qty=%d avg=%.2f side=%s",
                instrument, new_qty, pos["avg_price"], current_side,
            )

        return self._positions[instrument]

    def set_sl_tp(
        self,
        instrument: str,
        stop_loss: float,
        take_profit: float,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
    ) -> None:
        """Set SL/TP levels for a position (called by strategy_gen after fill)."""
        if instrument in self._positions:
            self._positions[instrument].update({
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
            })

    def update_trailing_sl(self, instrument: str, new_sl: float) -> None:
        """Update trailing stop-loss if the new level is tighter."""
        if instrument in self._positions:
            pos = self._positions[instrument]
            if pos["side"] == "long" and new_sl > pos["stop_loss"]:
                pos["stop_loss"] = new_sl
            elif pos["side"] == "short" and (new_sl < pos["stop_loss"] or pos["stop_loss"] == 0.0):
                pos["stop_loss"] = new_sl

    def reset(self) -> None:
        """Clear all positions (used in testing)."""
        self._positions.clear()

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset the singleton instance (used in testing)."""
        with cls._lock:
            cls._instance = None


# Module-level singleton access
position_registry = PositionRegistry()
