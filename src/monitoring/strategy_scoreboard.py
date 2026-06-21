import csv
import logging
import math
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCOREBOARD_PATH = Path("reports/attribution/strategy_scoreboard.csv")


class StrategyScoreboard:
    def __init__(
        self, db_path: str | Path = "state/order_state.db", output_path: str | Path = _SCOREBOARD_PATH
    ):
        self._db_path = Path(db_path)
        self._output_path = Path(output_path)

    def _fetch_all_trades(self) -> list[dict[str, Any]]:
        if not self._db_path.exists():
            return []
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT o.strategy, o.instrument, o.side, o.quantity, o.price,
                       f.fill_price, f.fill_quantity, f.filled_at,
                       f.slippage_bps
                FROM orders o
                JOIN fills f ON o.event_id = f.order_id
                ORDER BY o.strategy, f.filled_at ASC
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error("Failed to fetch trades: %s", e)
            return []

    def _group_by_strategy(
        self, trades: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            strategy = t.get("strategy") or "unknown"
            grouped.setdefault(strategy, []).append(t)
        return grouped

    def _calculate_strategy_metrics(
        self, strategy: str, trades: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not trades:
            return {
                "strategy": strategy,
                "trades": 0,
                "pnl": 0.0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "expectancy": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "slippage": 0.0,
            }

        pnl_sequence = []
        positions: dict[str, dict[str, Any]] = {}
        total_slippage = 0.0
        slippage_count = 0

        for trade in trades:
            inst = trade["instrument"]
            side = trade["side"].lower()
            qty = trade["fill_quantity"]
            price = trade["fill_price"]

            expected_price = trade.get("price")
            if expected_price:
                slip = (price - expected_price) if side == "buy" else (expected_price - price)
                total_slippage += slip
                slippage_count += 1

            if inst not in positions:
                positions[inst] = {"qty": 0, "avg_price": 0.0, "realized_pnl": 0.0}

            pos = positions[inst]
            if side == "buy":
                if pos["qty"] < 0:
                    covered = min(qty, abs(pos["qty"]))
                    trade_pnl = (pos["avg_price"] - price) * covered
                    pnl_sequence.append(trade_pnl)
                    pos["qty"] += qty
                else:
                    pos["qty"] += qty
                    pos["avg_price"] = price
            else:
                if pos["qty"] > 0:
                    sold = min(qty, pos["qty"])
                    trade_pnl = (price - pos["avg_price"]) * sold
                    pnl_sequence.append(trade_pnl)
                    pos["qty"] -= qty
                else:
                    pos["qty"] -= qty
                    pos["avg_price"] = price

        trades_count = len(pnl_sequence)
        total_pnl = sum(pnl_sequence)

        wins = [p for p in pnl_sequence if p > 0]
        losses = [p for p in pnl_sequence if p <= 0]

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))

        expectancy = total_pnl / trades_count if trades_count > 0 else 0.0
        profit_factor = (
            (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        )

        mean_pnl = expectancy
        variance = (
            sum((p - mean_pnl) ** 2 for p in pnl_sequence) / trades_count
            if trades_count > 1
            else 0
        )
        std_dev = math.sqrt(variance)
        sharpe = mean_pnl / std_dev if std_dev > 0 else 0.0

        downside = [p for p in pnl_sequence if p < 0]
        downside_var = (
            sum(p ** 2 for p in downside) / len(downside) if downside else 0
        )
        downside_std = math.sqrt(downside_var)
        sortino = mean_pnl / downside_std if downside_std > 0 else sharpe

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnl_sequence:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return {
            "strategy": strategy,
            "trades": trades_count,
            "pnl": total_pnl,
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "expectancy": round(expectancy, 4),
            "profit_factor": round(profit_factor, 4),
            "max_drawdown": round(max_dd, 4),
            "slippage": round(total_slippage / slippage_count, 4) if slippage_count > 0 else 0.0,
        }

    def update(self) -> Path:
        trades = self._fetch_all_trades()
        grouped = self._group_by_strategy(trades)
        rows = []
        for strategy, strategy_trades in grouped.items():
            metrics = self._calculate_strategy_metrics(strategy, strategy_trades)
            rows.append(metrics)

        rows.sort(key=lambda r: r.get("sharpe", 0.0), reverse=True)

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._output_path.open("w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "strategy",
                    "trades",
                    "pnl",
                    "sharpe",
                    "sortino",
                    "expectancy",
                    "profit_factor",
                    "max_drawdown",
                    "slippage",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["strategy"],
                        row["trades"],
                        row["pnl"],
                        row["sharpe"],
                        row["sortino"],
                        row["expectancy"],
                        row["profit_factor"],
                        row["max_drawdown"],
                        row["slippage"],
                    ]
                )

        logger.info("Strategy scoreboard updated: %s", self._output_path)
        return self._output_path

    def get_rankings(self) -> list[dict[str, Any]]:
        trades = self._fetch_all_trades()
        grouped = self._group_by_strategy(trades)
        rows = []
        for strategy, strategy_trades in grouped.items():
            metrics = self._calculate_strategy_metrics(strategy, strategy_trades)
            rows.append(metrics)
        rows.sort(key=lambda r: r.get("sharpe", 0.0), reverse=True)
        return rows

    def get_top(self, n: int) -> list[str]:
        rankings = self.get_rankings()
        return [r["strategy"] for r in rankings[:n]]


__all__ = ["StrategyScoreboard"]
