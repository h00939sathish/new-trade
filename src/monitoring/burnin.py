import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.risk.position_registry import position_registry


def build_paper_reconciliation_snapshot(system: Any) -> dict[str, Any]:
    execution = system.execution
    portfolio = system.portfolio_opt

    portfolio_positions = {
        symbol: int(data.get("quantity", 0))
        for symbol, data in portfolio._positions.items()
        if int(data.get("quantity", 0)) != 0
    }
    registry_positions = {
        symbol: int(data.get("quantity", 0))
        for symbol, data in position_registry.get_all_positions().items()
    }

    mismatches = {}
    for symbol in sorted(set(portfolio_positions) | set(registry_positions)):
        portfolio_qty = portfolio_positions.get(symbol, 0)
        registry_qty = registry_positions.get(symbol, 0)
        if portfolio_qty != registry_qty:
            mismatches[symbol] = {
                "portfolio": portfolio_qty,
                "registry": registry_qty,
            }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "mismatch" if mismatches else "ok",
        "paper_trading": bool(execution._paper_trading),
        "open_orders": len(execution._open_orders),
        "filled_orders": sum(len(fills) for fills in execution._filled_orders.values()),
        "portfolio_positions": portfolio_positions,
        "registry_positions": registry_positions,
        "position_mismatches": mismatches,
    }


def write_paper_reconciliation_snapshot(system: Any, path: Path) -> dict[str, Any]:
    snapshot = build_paper_reconciliation_snapshot(system)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(snapshot) + "\n")
    return snapshot


async def run_paper_reconciliation_loop(
    system: Any,
    path: Path,
    interval_seconds: float = 30 * 60,
) -> None:
    while True:
        write_paper_reconciliation_snapshot(system, path)
        await asyncio.sleep(interval_seconds)
