import argparse
import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


_DEFAULT_DB = Path("state/order_state.db")


def export_trade_journal(
    db_path: Path = _DEFAULT_DB,
    output_format: str = "csv",
    from_date: str | None = None,
    output_file: str | None = None,
) -> str:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    query = """
        SELECT
            o.event_id,
            o.instrument,
            o.exchange,
            o.side,
            o.order_type,
            o.quantity,
            o.price,
            o.broker_order_id,
            o.strategy,
            o.signal_id,
            o.created_at,
            o.updated_at,
            f.fill_price,
            f.fill_quantity,
            f.filled_at
        FROM orders o
        LEFT JOIN fills f ON o.event_id = f.order_id
        WHERE o.status = 'filled'
    """
    params: list[str] = []
    if from_date:
        query += " AND o.created_at >= ?"
        params.append(from_date)
    query += " ORDER BY o.created_at ASC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    records = []
    for r in rows:
        fill_price = r["fill_price"] if r["fill_price"] else r["price"]
        fill_qty = r["fill_quantity"] if r["fill_quantity"] else r["quantity"]
        notional = (fill_qty or 0) * (fill_price or 0)
        records.append(
            {
                "timestamp": r["filled_at"] or r["updated_at"],
                "event_id": r["event_id"],
                "instrument": r["instrument"],
                "exchange": r["exchange"],
                "side": r["side"],
                "order_type": r["order_type"],
                "quantity": fill_qty,
                "price": fill_price,
                "notional": round(notional, 2),
                "broker_order_id": r["broker_order_id"] or "",
                "strategy": r["strategy"] or "",
                "signal_id": r["signal_id"] or "",
                "created_at": r["created_at"],
            }
        )

    if output_format == "json":
        result = json.dumps(records, indent=2, default=str)
    else:
        if not records:
            return ""
        result = _to_csv(records)

    if output_file:
        Path(output_file).write_text(result, encoding="utf-8")
    return result


def _to_csv(records: list[dict]) -> str:
    if not records:
        return ""
    fields = list(records[0].keys())
    lines = [",".join(fields)]
    for rec in records:
        lines.append(
            ",".join(
                f'"{str(rec.get(f, "")).replace(chr(34), chr(34) + chr(34))}"'
                for f in fields
            )
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export trade journal from order DB")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--from", dest="from_date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--output", "-o", type=str, help="Output file path")
    parser.add_argument("--db", type=str, default=str(_DEFAULT_DB), help="Path to order DB")
    args = parser.parse_args()

    result = export_trade_journal(
        db_path=Path(args.db),
        output_format=args.format,
        from_date=args.from_date,
        output_file=args.output,
    )
    if not args.output:
        print(result)


if __name__ == "__main__":
    main()
