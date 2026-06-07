"""
P2.2 — Per-strategy attribution aggregator.

Reads FILL events (which carry the `strategy` field set in
_execute_approved_signal commit ebdd65f) and aggregates per-strategy
metrics:

  - total PnL
  - Sharpe ratio (rolling, 20-trade window)
  - profit factor (gross_wins / |gross_losses|)
  - expectancy per trade (mean PnL)
  - win rate
  - signal count, fill count

Output: logs/attribution_<date>.jsonl, one entry per day, plus a
real-time summary returned from get_summary().

This is read-only over the event store and the position registry.
It does NOT modify any system state. It is safe to run in parallel
with the live system.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("analytics.attribution")


class AttributionAggregator:
    """Aggregates per-strategy PnL from FILL events."""

    def __init__(self, db_path: str | Path = "state/trading_events.db"):
        self.db_path = Path(db_path)
        # {strategy: {"trades": [...], "signals": 0, "fills": 0}}
        self._state: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"trades": [], "signals": 0, "fills": 0, "wins": 0, "losses": 0}
        )

    def add_fill(self, fill_data: dict[str, Any]) -> None:
        """Record a fill. PnL is computed from sell - buy on round-trips.

        For attribution, we accumulate realized PnL only on sell fills
        (since buy fills don't realize a gain). Each sell fill's PnL
        is computed as (fill_price - average_buy_price) * fill_qty,
        which is exactly what portfolio_opt's _on_fill does on SSOT
        registry data.
        """
        strategy = fill_data.get("strategy") or "unknown"
        side = fill_data.get("side", "buy")
        qty = int(fill_data.get("fill_quantity", 0))
        price = float(fill_data.get("fill_price", 0.0))

        if side == "buy":
            # Record cost basis; don't realize PnL
            self._state[strategy]["trades"].append(
                {
                    "side": "buy",
                    "qty": qty,
                    "price": price,
                    "pnl": 0.0,
                    "ts": fill_data.get("timestamp"),
                }
            )
        else:  # sell
            # For attribution we use a simple FIFO approximation:
            # realized PnL = (price - avg_buy_price) * qty
            avg_buy = self._avg_buy_price(strategy)
            pnl = (price - avg_buy) * qty if avg_buy else 0.0
            self._state[strategy]["trades"].append(
                {
                    "side": "sell",
                    "qty": qty,
                    "price": price,
                    "pnl": pnl,
                    "ts": fill_data.get("timestamp"),
                }
            )
            if pnl > 0:
                self._state[strategy]["wins"] += 1
            elif pnl < 0:
                self._state[strategy]["losses"] += 1
        self._state[strategy]["fills"] += 1

    def add_signal(self, strategy: str) -> None:
        self._state[strategy]["signals"] += 1

    def _avg_buy_price(self, strategy: str) -> float:
        buys = [t for t in self._state[strategy]["trades"] if t["side"] == "buy"]
        if not buys:
            return 0.0
        total_cost = sum(t["qty"] * t["price"] for t in buys)
        total_qty = sum(t["qty"] for t in buys)
        return total_cost / total_qty if total_qty > 0 else 0.0

    def get_summary(self) -> dict[str, dict[str, Any]]:
        """Return per-strategy attribution summary."""
        out: dict[str, dict[str, Any]] = {}
        for strategy, state in self._state.items():
            pnls = [t["pnl"] for t in state["trades"] if t["side"] == "sell"]
            total_pnl = sum(pnls)
            n = len(pnls)
            win_pnls = [p for p in pnls if p > 0]
            loss_pnls = [p for p in pnls if p < 0]
            gross_wins = sum(win_pnls)
            gross_losses = abs(sum(loss_pnls))
            profit_factor = (
                gross_wins / gross_losses
                if gross_losses > 0
                else float("inf")
                if gross_wins > 0
                else 0.0
            )
            win_rate = state["wins"] / n if n > 0 else 0.0
            expectancy = total_pnl / n if n > 0 else 0.0
            sharpe = self._rolling_sharpe(pnls, window=20) if len(pnls) >= 5 else 0.0
            out[strategy] = {
                "fills": state["fills"],
                "signals": state["signals"],
                "trades": n,
                "wins": state["wins"],
                "losses": state["losses"],
                "win_rate": round(win_rate, 4),
                "total_pnl": round(total_pnl, 2),
                "expectancy": round(expectancy, 2),
                "profit_factor": round(profit_factor, 4) if math.isfinite(profit_factor) else None,
                "sharpe_20": round(sharpe, 4),
            }
        return out

    def _rolling_sharpe(self, pnls: list[float], window: int) -> float:
        """Sharpe over the most recent `window` trades (no risk-free rate)."""
        recent = pnls[-window:] if len(pnls) >= window else pnls
        if len(recent) < 2:
            return 0.0
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / (len(recent) - 1)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        # Annualize: assume 252 trading days × N trades/day. Conservative
        # scaling: use sqrt(N) for the period.
        return mean / std

    def load_from_db(self, since: str | None = None) -> None:
        """Bootstrap state by replaying FILL events from the SQLite event store."""
        if not self.db_path.exists():
            logger.warning("Event DB not found: %s", self.db_path)
            return
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            sql = "SELECT data, timestamp FROM events WHERE event_type='order.fill' "
            params: tuple = ()
            if since:
                sql += " AND timestamp >= ?"
                params = (since,)
            sql += " ORDER BY timestamp ASC"
            cursor.execute(sql, params)
            for data_blob, ts in cursor.fetchall():
                try:
                    payload = json.loads(data_blob)
                except Exception:
                    continue
                payload.setdefault("timestamp", ts)
                self.add_fill(payload)
            # Also count signals
            cursor.execute(
                "SELECT data FROM events WHERE event_type='signal.generated' "
                + ("AND timestamp >= ? " if since else "")
                + "ORDER BY timestamp ASC",
                params if since else (),
            )
            for (data_blob,) in cursor.fetchall():
                try:
                    payload = json.loads(data_blob)
                except Exception:
                    continue
                self.add_signal(payload.get("strategy", "unknown"))
        finally:
            conn.close()

    def write_daily_report(self, out_dir: str | Path = "logs") -> Path:
        """Write today's attribution summary to logs/attribution_<date>.jsonl."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        path = out_dir / f"attribution_{date_str}.jsonl"
        summary = {
            "date": date_str,
            "generated_at": datetime.now(UTC).isoformat(),
            "per_strategy": self.get_summary(),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
        return path
