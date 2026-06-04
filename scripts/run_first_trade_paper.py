#!/usr/bin/env python3
"""
P0.5 — First Trade Paper Run

Goal: produce ONE complete paper round-trip.

Signal → Risk Approval → Order → Fill → Position → Exit → PnL

This script starts the full TradingSystem in paper mode, subscribes to
the FILL event, and exits as soon as one complete BUY→SELL cycle is
observed (or after MAX_RUNTIME_MINUTES, or after MAX_RISK_BREACHES).

Usage:
    python scripts/run_first_trade_paper.py

Watchlist defaults to RELIANCE (single symbol, deterministic).
Set TRA_WATCHLIST env var to override.

Preconditions for this script to work:
    - P0.1 and P0.2 applied (passed scope + _capital init)
    - P0.4 applied (only 3 strategies enabled)
    - Run during IST market hours (9:15-15:30) for live Yahoo data
"""
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

# Resolve repo root and add to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.system import TradingSystem
from src.schemas.events import EventType, FillEvent
from src.risk.position_registry import position_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("first_trade_paper")

# ── Tunables ──────────────────────────────────────────────────────────
WATCHLIST = os.getenv("TRA_WATCHLIST", "RELIANCE").split(",")
MAX_RUNTIME_MINUTES = int(os.getenv("TRA_MAX_RUNTIME_MINUTES", "30"))
MAX_RISK_BREACHES = int(os.getenv("TRA_MAX_RISK_BREACHES", "3"))
LOG_PATH = ROOT / "logs" / f"first_trade_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.jsonl"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── State ─────────────────────────────────────────────────────────────
fills: list[dict] = []
orders: list[dict] = []
risk_breaches: list[dict] = []
signals: list[dict] = []
stop_event = asyncio.Event()


def _log_event(event_type: str, payload: dict) -> None:
    """Append a structured record to the JSONL log."""
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kind": event_type,
        **payload,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _summarize_position_after_fill(fill: FillEvent) -> None:
    pos = position_registry.get_position(fill.instrument)
    _log_event(
        "position_after_fill",
        {
            "instrument": fill.instrument,
            "quantity": pos["quantity"],
            "avg_price": pos["avg_price"],
            "side": pos.get("side"),
        },
    )


async def _watch_fills(system: TradingSystem) -> None:
    """Subscribe to FILL events, record them, signal stop on full round-trip."""
    bus = system.market_intel.event_store  # the event store is shared via bus
    # Use the bus to subscribe directly
    from src.event_store.async_bus import event_bus

    queue = event_bus.subscribe("first_trade_watcher", {EventType.FILL, EventType.SIGNAL, EventType.RISK_BREACH, EventType.ORDER_CREATED})
    logger.info("Subscribed to FILL/SIGNAL/RISK_BREACH/ORDER_CREATED")

    while not stop_event.is_set():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if event.event_type == EventType.FILL:
            data = event.data
            fill_record = {
                "instrument": data.get("instrument"),
                "side": data.get("side"),
                "fill_price": data.get("fill_price"),
                "fill_quantity": data.get("fill_quantity"),
                "commission": data.get("commission"),
                "slippage_bps": data.get("slippage_bps"),
                "signal_id": data.get("signal_id"),
                "strategy": data.get("strategy"),
                "order_id": data.get("order_id"),
            }
            fills.append(fill_record)
            _log_event("fill", fill_record)
            logger.info(
                "FILL #%d: %s %s %d @ %.2f (commission=%.2f, slippage=%.1fbps)",
                len(fills),
                fill_record["side"],
                fill_record["instrument"],
                fill_record["fill_quantity"],
                fill_record["fill_price"],
                fill_record["commission"] or 0.0,
                fill_record["slippage_bps"] or 0.0,
            )
            _summarize_position_after_fill(event)

            # Check for complete round-trip: at least one BUY and one SELL
            sides = {f["side"] for f in fills}
            if {"buy", "sell"}.issubset(sides):
                logger.info("=== ROUND-TRIP COMPLETE (BUY + SELL observed) ===")
                stop_event.set()
                return

        elif event.event_type == EventType.SIGNAL:
            data = event.data
            sig_record = {
                "instrument": data.get("instrument"),
                "direction": data.get("direction"),
                "confidence": data.get("confidence"),
                "strategy": data.get("strategy"),
                "price": data.get("price"),
            }
            signals.append(sig_record)
            _log_event("signal", sig_record)
            logger.info(
                "SIGNAL: %s %s @ %.2f confidence=%.2f strategy=%s",
                sig_record["instrument"],
                sig_record["direction"],
                sig_record["price"] or 0.0,
                sig_record["confidence"],
                sig_record["strategy"],
            )

        elif event.event_type == EventType.RISK_BREACH:
            data = event.data
            breach_record = {
                "instrument": data.get("instrument"),
                "check_name": data.get("check_name"),
                "passed": data.get("passed"),
                "checks": data.get("details", {}).get("checks", []),
            }
            risk_breaches.append(breach_record)
            _log_event("risk_breach", breach_record)
            logger.warning(
                "RISK_BREACH #%d: %s instrument=%s",
                len(risk_breaches),
                breach_record["check_name"],
                breach_record["instrument"],
            )
            if len(risk_breaches) >= MAX_RISK_BREACHES:
                logger.warning("Reached MAX_RISK_BREACHES=%d, stopping.", MAX_RISK_BREACHES)
                stop_event.set()
                return

        elif event.event_type == EventType.ORDER_CREATED:
            data = event.data
            order_record = {
                "instrument": data.get("instrument"),
                "side": data.get("side"),
                "quantity": data.get("quantity"),
                "price": data.get("price"),
                "order_id": data.get("order_id") or data.get("event_id"),
                "status": data.get("status"),
            }
            orders.append(order_record)
            _log_event("order_created", order_record)
            logger.info(
                "ORDER: %s %s %d @ %.2f status=%s",
                order_record["instrument"],
                order_record["side"],
                order_record["quantity"],
                order_record["price"] or 0.0,
                order_record["status"],
            )


async def _timeout_watcher() -> None:
    """Set stop_event after MAX_RUNTIME_MINUTES."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=MAX_RUNTIME_MINUTES * 60)
    except asyncio.TimeoutError:
        logger.warning("Reached MAX_RUNTIME_MINUTES=%d, stopping.", MAX_RUNTIME_MINUTES)
        stop_event.set()


def _print_summary() -> None:
    """Print end-of-run summary to stdout and log."""
    print("\n" + "=" * 60)
    print("FIRST TRADE PAPER RUN — SUMMARY")
    print("=" * 60)
    print(f"Watchlist:           {WATCHLIST}")
    print(f"Signals emitted:     {len(signals)}")
    print(f"Orders created:      {len(orders)}")
    print(f"Fills observed:      {len(fills)}")
    print(f"Risk breaches:       {len(risk_breaches)}")
    print(f"Log file:            {LOG_PATH}")

    if len(fills) >= 2:
        buy = next((f for f in fills if f["side"] == "buy"), None)
        sell = next((f for f in fills if f["side"] == "sell"), None)
        if buy and sell:
            qty = min(buy["fill_quantity"], sell["fill_quantity"])
            gross_pnl = (sell["fill_price"] - buy["fill_price"]) * qty
            total_commission = (buy["commission"] or 0) + (sell["commission"] or 0)
            net_pnl = gross_pnl - total_commission
            print()
            print(f"Round-trip details:")
            print(f"  BUY  {qty:>4} @ ₹{buy['fill_price']:.2f}  commission=₹{buy['commission']:.2f}")
            print(f"  SELL {qty:>4} @ ₹{sell['fill_price']:.2f}  commission=₹{sell['commission']:.2f}")
            print(f"  Gross PnL:  ₹{gross_pnl:.2f}")
            print(f"  Net PnL:    ₹{net_pnl:.2f}")

            # Cross-check against position_registry
            pos = position_registry.get_position(buy["instrument"])
            print()
            print(f"Position registry says: qty={pos['quantity']} (should be 0 if fully closed)")
    else:
        print()
        print("No round-trip completed. Inspect the log for details.")
    print("=" * 60)


async def main() -> int:
    logger.info("=" * 60)
    logger.info("FIRST TRADE PAPER RUN — STAGE 1 P0.5")
    logger.info("=" * 60)
    logger.info("Watchlist: %s", WATCHLIST)
    logger.info("Max runtime: %d min", MAX_RUNTIME_MINUTES)
    logger.info("Log file: %s", LOG_PATH)
    logger.info("Preconditions: P0.1, P0.2, P0.4 applied")

    # Force paper mode
    os.environ["TRA_LIVE_TRADING_ENABLED"] = "false"
    os.environ["TRA_KITE_API_KEY"] = ""
    os.environ["TRA_KITE_API_SECRET"] = ""
    os.environ["TRA_KITE_ACCESS_TOKEN"] = ""
    os.environ["TRA_DASHBOARD"] = "0"  # No CLI dashboard; log is the output
    os.environ["TRA_DASHBOARD_TYPE"] = "http"

    system = TradingSystem()
    system.set_watchlist(WATCHLIST)

    # Install signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig_id in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_id, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await system.start()
        logger.info("System started. Watching for events...")

        # Run watcher and timeout concurrently
        await asyncio.gather(
            _watch_fills(system),
            _timeout_watcher(),
        )
    except Exception:
        logger.exception("Run failed")
        return 1
    finally:
        try:
            await system.stop()
        except Exception:
            logger.exception("Error during system.stop()")

    _print_summary()
    return 0 if len(fills) >= 2 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
