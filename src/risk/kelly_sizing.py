import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("risk.kelly_sizing")


class KellySizer:
    """Fractional Kelly position sizer.

    Dynamically computes win rate (p) and average win/loss ratio (b)
    from historical trades database and returns the Kelly sizing factor.
    """

    def __init__(
        self,
        db_path: str | Path = "state/order_state.db",
        fractional_kelly: float = 0.25,
        max_allocation_pct: float = 0.10,
    ):
        self.db_path = Path(db_path)
        self.fractional_kelly = fractional_kelly
        self.max_allocation_pct = max_allocation_pct

    def get_strategy_performance(
        self,
        strategy: str,
        default_p: float = 0.50,
        default_b: float = 1.5,
    ) -> tuple[float, float]:
        """Calculate win rate (p) and win/loss ratio (b) for a strategy from orders/fills DB.

        Falls back to defaults if there is insufficient history (< 5 completed trades).
        """
        if not self.db_path.exists():
            return default_p, default_b

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Retrieve all fills for this strategy by joining orders and fills
            cursor.execute(
                """
                SELECT f.instrument, f.side, f.fill_price, f.fill_quantity, f.filled_at
                FROM fills f
                JOIN orders o ON f.order_id = o.event_id
                WHERE o.strategy = ?
                ORDER BY f.filled_at ASC
                """,
                (strategy,),
            )

            rows = cursor.fetchall()
            conn.close()

            if len(rows) < 10:  # Need at least 5 completed trades (10 fills)
                return default_p, default_b

            # Reconstruct FIFO trades per instrument to calculate realized PnLs
            instrument_fills: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                inst = row["instrument"]
                instrument_fills.setdefault(inst, []).append(
                    {
                        "side": row["side"].lower(),
                        "price": float(row["fill_price"]),
                        "qty": int(row["fill_quantity"]),
                    }
                )

            trades_pnl: list[float] = []
            for inst, fills in instrument_fills.items():
                buys: list[dict[str, Any]] = []
                sells: list[dict[str, Any]] = []
                for fill in fills:
                    if fill["side"] == "buy":
                        buys.append(fill)
                    else:
                        sells.append(fill)

                    # Match buys and sells using FIFO
                    while buys and sells:
                        b = buys[0]
                        s = sells[0]
                        match_qty = min(b["qty"], s["qty"])

                        # Realized PnL = (sell_price - buy_price) * quantity
                        # This works symmetrically for both long and short matched positions
                        pnl = (s["price"] - b["price"]) * match_qty
                        trades_pnl.append(pnl)

                        b["qty"] -= match_qty
                        s["qty"] -= match_qty
                        if b["qty"] == 0:
                            buys.pop(0)
                        if s["qty"] == 0:
                            sells.pop(0)

            if len(trades_pnl) < 5:
                return default_p, default_b

            # Calculate p (win rate) and b (average win / average loss)
            wins = [p for p in trades_pnl if p > 0]
            losses = [p for p in trades_pnl if p < 0]

            p = len(wins) / len(trades_pnl)

            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0

            b = avg_win / avg_loss if avg_loss > 0 else default_b

            if b <= 0.1:
                b = default_b

            return p, b
        except Exception as e:
            logger.error("Error calculating strategy performance for %s: %s", strategy, e)
            return default_p, default_b

    def calculate_kelly_fraction(self, p: float, b: float) -> float:
        """Standard Kelly sizing formula: f* = p - (1 - p) / b."""
        if b <= 0:
            return 0.0
        kelly_f = p - (1.0 - p) / b
        return max(0.0, min(kelly_f, 1.0))

    def get_position_sizing_factor(
        self,
        strategy: str,
        default_p: float = 0.50,
        default_b: float = 1.5,
    ) -> float:
        """Calculate dynamic sizing multiplier based on fractional Kelly."""
        p, b = self.get_strategy_performance(strategy, default_p, default_b)
        f_star = self.calculate_kelly_fraction(p, b)
        multiplier = self.fractional_kelly * f_star
        logger.info(
            "Kelly sizing for strategy %s: p=%.2f, b=%.2f, f*=%.2f, multiplier=%.2f (fractional=%.2f)",
            strategy,
            p,
            b,
            f_star,
            multiplier,
            self.fractional_kelly,
        )
        return multiplier
