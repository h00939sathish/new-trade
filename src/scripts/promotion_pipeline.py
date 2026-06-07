import argparse
import logging
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("promotion_pipeline")


def check_strategies(
    db_path: str, min_trades: int = 30, min_sharpe: float = 1.2, max_drawdown_pct: float = 10.0
):
    if not Path(db_path).exists():
        logger.error(f"Database {db_path} not found.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query all fills to calculate PnL per strategy
    cursor.execute("""
        SELECT strategy, instrument, side, fill_price, fill_quantity, timestamp
        FROM fills
        ORDER BY timestamp ASC
    """)
    rows = cursor.fetchall()

    # We will simulate the PnL sequence for each strategy
    strategy_pnls = defaultdict(list)
    strategy_positions = defaultdict(lambda: {"qty": 0, "avg_cost": 0.0})

    for row in rows:
        strat = row["strategy"]
        if not strat or strat == "unknown":
            continue

        sym = row["instrument"]
        side = row["side"]
        qty = row["fill_quantity"]
        price = row["fill_price"]

        pos = strategy_positions[(strat, sym)]
        if side == "buy":
            total_cost = (pos["avg_cost"] * pos["qty"]) + (price * qty)
            pos["qty"] += qty
            pos["avg_cost"] = total_cost / pos["qty"]
        else:
            if pos["qty"] >= qty:
                realized = (price - pos["avg_cost"]) * qty
                pos["qty"] -= qty
                if pos["qty"] == 0:
                    pos["avg_cost"] = 0.0
                strategy_pnls[strat].append(realized)

    promoted = []

    print("=" * 60)
    print(f"{'Strategy Name':<35} {'Trades':<8} {'Win%':<8} {'Sharpe':<8}")
    print("=" * 60)

    for strat, pnls in strategy_pnls.items():
        if len(pnls) < min_trades:
            continue

        wins = sum(1 for p in pnls if p > 0)
        win_rate = (wins / len(pnls)) * 100

        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
        std_pnl = variance**0.5

        # Approximate annualized sharpe assuming ~5 trades a day = ~1250 trades a year
        # Actually standard ratio is mean / std
        sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0

        print(f"{strat:<35} {len(pnls):<8} {win_rate:<7.1f}% {sharpe:<7.2f}")

        if sharpe >= min_sharpe:
            promoted.append(strat)

    print("=" * 60)
    print(f"Eligible for Live Trading (Sharpe >= {min_sharpe}, Trades >= {min_trades}):")
    if not promoted:
        print("None")
    for p in promoted:
        print(f"- {p} [PASSED]")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Evaluate paper trading strategies for live promotion"
    )
    parser.add_argument(
        "--db", type=str, default="state/trading_events.db", help="Path to SQLite events DB"
    )
    parser.add_argument("--min-trades", type=int, default=30, help="Minimum trades required")
    parser.add_argument(
        "--min-sharpe", type=float, default=1.2, help="Minimum Sharpe Ratio required"
    )
    args = parser.parse_args()

    check_strategies(args.db, min_trades=args.min_trades, min_sharpe=args.min_sharpe)
