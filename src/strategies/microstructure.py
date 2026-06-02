import logging
from typing import Any

import numpy as np

from src.strategies.base import Strategy

logger = logging.getLogger("strategy.microstructure")


class OrderFlowImbalanceStrategy(Strategy):
    """Microstructure Strategy using Order Flow Imbalance (OFI) and Bid-Ask Volume Pressure."""

    def __init__(self, ofi_window: int = 20, threshold: float = 1.5):
        self.name = "microstructure"
        self.data_type = "tick"
        self.timeframe = "tick"
        self.ofi_window = ofi_window
        self.threshold = threshold

        # Track previous tick best bid/ask quotes: instrument -> (bid_price, bid_qty, ask_price, ask_qty)
        self._prev_quotes: dict[str, tuple[float, int, float, int]] = {}
        # Track OFI values list per instrument
        self._ofi_history: dict[str, list[float]] = {}

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        depth: dict[str, list[dict[str, Any]]] | None = None,
        bid: float | None = None,
        ask: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if depth is None or bid is None or ask is None:
            return None

        buy_levels = depth.get("buy", [])
        sell_levels = depth.get("sell", [])
        if not buy_levels or not sell_levels:
            return None

        # Extract top level bid/ask quantities
        bid_price = float(bid)
        ask_price = float(ask)
        bid_qty = int(buy_levels[0].get("quantity", 0))
        ask_qty = int(sell_levels[0].get("quantity", 0))

        # 1. Calculate OFI (Order Flow Imbalance)
        prev = self._prev_quotes.get(instrument)
        ofi = 0.0
        if prev is not None:
            prev_bid_price, prev_bid_qty, prev_ask_price, prev_ask_qty = prev

            # Bid side change
            if bid_price > prev_bid_price:
                delta_v_bid = bid_qty
            elif bid_price < prev_bid_price:
                delta_v_bid = -bid_qty
            else:
                delta_v_bid = bid_qty - prev_bid_qty

            # Ask side change
            if ask_price > prev_ask_price:
                delta_v_ask = -ask_qty
            elif ask_price < prev_ask_price:
                delta_v_ask = ask_qty
            else:
                delta_v_ask = ask_qty - prev_ask_qty

            ofi = float(delta_v_bid - delta_v_ask)

        self._prev_quotes[instrument] = (bid_price, bid_qty, ask_price, ask_qty)

        # Update OFI history
        self._ofi_history.setdefault(instrument, []).append(ofi)
        history = self._ofi_history[instrument]
        if len(history) > self.ofi_window:
            history.pop(0)

        if len(history) < self.ofi_window:
            return None

        # Standardize OFI
        mean_ofi = np.mean(history)
        std_ofi = np.std(history)

        z_ofi = (ofi - mean_ofi) / std_ofi if std_ofi > 0 else 0.0

        # 2. Calculate Bid-Ask Volume Pressure
        total_qty = bid_qty + ask_qty
        pressure = bid_qty / total_qty if total_qty > 0 else 0.5

        direction = None
        confidence = 0.0

        if z_ofi > self.threshold and pressure > 0.65:
            direction = "long"
            confidence = min(0.5 + (pressure - 0.65) * 1.0, 0.90)
        elif z_ofi < -self.threshold and pressure < 0.35:
            direction = "short"
            confidence = min(0.5 + (0.35 - pressure) * 1.0, 0.90)

        if direction is None:
            return None

        return {
            "direction": direction,
            "confidence": confidence,
            "price": prices[-1],
            "features": {
                "ofi": ofi,
                "z_ofi": float(z_ofi),
                "bid_ask_pressure": float(pressure),
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
            },
        }
