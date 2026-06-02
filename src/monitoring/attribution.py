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
