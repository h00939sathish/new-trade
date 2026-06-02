import logging
import sqlite3
import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings
from src.schemas.events import FillEvent

logger = logging.getLogger("monitoring.attribution")

class AttributionLogger:
    """Logs attribution (PnL per strategy) and generates SEBI compliance audit trails."""

    def __init__(self, db_path: str | Path = "state/order_state.db", report_dir: str | Path = "reports/sebi"):
        self.db_path = Path(db_path)
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        
    def log_fill(self, event: FillEvent) -> None:
        """Log a fill event for attribution tracking."""
        strategy = event.strategy or "unknown"
        logger.info(
            "ATTRIBUTION | Strategy: %s | Instrument: %s | Side: %s | Qty: %d | Price: %.2f | Order ID: %s",
            strategy,
            event.instrument,
            event.side.value,
            event.fill_quantity,
            event.fill_price,
            event.data.get("order_id", ""),
        )

    def generate_sebi_report(self, date_str: str | None = None) -> Path | None:
        """Generate a SEBI-compliant daily audit trail report."""
        if not self.db_path.exists():
            logger.warning("Cannot generate SEBI report: %s does not exist", self.db_path)
            return None

        if date_str is None:
            date_str = datetime.now(UTC).strftime("%Y-%m-%d")

        report_path = self.report_dir / f"sebi_audit_trail_{date_str}.csv"
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Query all orders and their fills for the given date
            cursor.execute(
                """
                SELECT o.event_id as order_id, o.created_at, o.instrument, o.side, 
                       o.order_type, o.quantity as order_qty, o.price as order_price,
                       o.strategy, o.status,
                       f.fill_id, f.filled_at, f.fill_quantity, f.fill_price
                FROM orders o
                LEFT JOIN fills f ON o.event_id = f.order_id
                WHERE date(o.created_at) = ? OR date(f.filled_at) = ?
                ORDER BY o.created_at ASC
                """,
                (date_str, date_str)
            )
            
            rows = cursor.fetchall()
            conn.close()
            
            with report_path.open("w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([
                    "Order ID", "Timestamp", "Instrument", "Side", "Order Type", 
                    "Order Qty", "Order Price", "Strategy", "Status",
                    "Fill ID", "Fill Timestamp", "Fill Qty", "Fill Price"
                ])
                for row in rows:
                    writer.writerow([
                        row["order_id"], row["created_at"], row["instrument"], row["side"].upper(),
                        row["order_type"].upper(), row["order_qty"], row["order_price"] or "",
                        row["strategy"], row["status"].upper(),
                        row["fill_id"] or "", row["filled_at"] or "", 
                        row["fill_quantity"] or "", row["fill_price"] or ""
                    ])
                    
            logger.info("SEBI audit trail generated: %s", report_path)
            return report_path
        except Exception as e:
            logger.error("Failed to generate SEBI report: %s", e)
            return None

class StrategyPerformanceTracker:
    """Calculates granular performance metrics per strategy from the trade DB."""
    
    def __init__(self, db_path: str | Path = "state/order_state.db"):
        self.db_path = Path(db_path)
        
    def _fetch_trades(self, strategy: str) -> list[dict]:
        """Fetch all filled orders for a specific strategy."""
        if not self.db_path.exists():
            return []
            
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT o.instrument, o.side, o.quantity, o.price, 
                       f.fill_price, f.fill_quantity, f.filled_at
                FROM orders o
                JOIN fills f ON o.event_id = f.order_id
                WHERE o.strategy = ?
                ORDER BY f.filled_at ASC
                """,
                (strategy,)
            )
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error("Failed to fetch trades for %s: %s", strategy, e)
            return []

    def calculate_metrics(self, strategy: str) -> dict:
        """Calculate performance metrics for a strategy based on filled orders."""
        trades = self._fetch_trades(strategy)
        
        if not trades:
            return {
                "trades_count": 0, "win_rate": 0.0, "expectancy": 0.0,
                "profit_factor": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
                "avg_slippage": 0.0, "avg_holding_time_min": 0.0
            }
            
        # Simplified pairing logic for PnL calculation (FIFO per instrument)
        # In a real system, you'd match buys and sells precisely.
        # Here we approximate by grouping fills and calculating realized PnL.
        pnl_sequence = []
        positions = {}
        total_slippage = 0.0
        slippage_count = 0
        
        for trade in trades:
            inst = trade["instrument"]
            side = trade["side"].lower()
            qty = trade["fill_quantity"]
            price = trade["fill_price"]
            
            # Calculate Slippage (fill vs intended order price)
            if trade["price"]:
                expected = trade["price"]
                slip = (price - expected) if side == "buy" else (expected - price)
                total_slippage += slip
                slippage_count += 1
            
            if inst not in positions:
                positions[inst] = {"qty": 0, "avg_price": 0.0, "realized_pnl": 0.0}
                
            pos = positions[inst]
            if side == "buy":
                if pos["qty"] < 0:
                    # Covering short
                    covered_qty = min(qty, abs(pos["qty"]))
                    trade_pnl = (pos["avg_price"] - price) * covered_qty
                    pnl_sequence.append(trade_pnl)
                    pos["qty"] += qty
                else:
                    pos["qty"] += qty
                    pos["avg_price"] = price # Simplified avg price
            else:
                if pos["qty"] > 0:
                    # Selling long
                    sold_qty = min(qty, pos["qty"])
                    trade_pnl = (price - pos["avg_price"]) * sold_qty
                    pnl_sequence.append(trade_pnl)
                    pos["qty"] -= qty
                else:
                    pos["qty"] -= qty
                    pos["avg_price"] = price

        wins = [p for p in pnl_sequence if p > 0]
        losses = [p for p in pnl_sequence if p <= 0]
        
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        
        trades_count = len(pnl_sequence)
        win_rate = len(wins) / trades_count if trades_count > 0 else 0.0
        expectancy = (sum(pnl_sequence) / trades_count) if trades_count > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        
        # Approximate Sharpe Ratio (assuming daily RF=0, using trade returns)
        import math
        mean_pnl = expectancy
        variance = sum((p - mean_pnl) ** 2 for p in pnl_sequence) / trades_count if trades_count > 1 else 0
        std_dev = math.sqrt(variance)
        sharpe = (mean_pnl / std_dev) if std_dev > 0 else 0.0
        
        # Max Drawdown
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
            "trades_count": trades_count,
            "win_rate": win_rate,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "avg_slippage": (total_slippage / slippage_count) if slippage_count > 0 else 0.0,
            "avg_holding_time_min": 0.0 # Placeholder for holding time calculation
        }

class PromotionGate:
    """Evaluates strategy metrics against hard performance thresholds to gate live promotion."""
    
    MIN_SHARPE = 1.2
    MIN_PROFIT_FACTOR = 1.3
    MIN_TRADES = 30
    MIN_EXPECTANCY = 0.0
    
    def __init__(self, db_path: str | Path = "state/order_state.db"):
        self.tracker = StrategyPerformanceTracker(db_path)
        
    def evaluate(self, strategy: str) -> tuple[bool, str]:
        """Evaluate if a strategy is fit for live promotion."""
        metrics = self.tracker.calculate_metrics(strategy)
        
        if metrics["trades_count"] < self.MIN_TRADES:
            return False, f"Insufficient trades: {metrics['trades_count']} < {self.MIN_TRADES}"
            
        if metrics["sharpe"] < self.MIN_SHARPE:
            return False, f"Sharpe too low: {metrics['sharpe']:.2f} < {self.MIN_SHARPE}"
            
        if metrics["profit_factor"] < self.MIN_PROFIT_FACTOR:
            return False, f"Profit Factor too low: {metrics['profit_factor']:.2f} < {self.MIN_PROFIT_FACTOR}"
            
        if metrics["expectancy"] <= self.MIN_EXPECTANCY:
            return False, f"Negative or zero expectancy: {metrics['expectancy']:.2f}"
            
        return True, "Passed all promotion gates."
