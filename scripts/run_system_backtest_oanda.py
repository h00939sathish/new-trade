#!/usr/bin/env python3
"""Backtest OANDA FX instruments (XAU/USD, EUR/USD) using Yahoo Finance data."""
import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.event_store.async_bus as async_bus_module
from src.backtest.sync_bus import SyncEventBus
from src.config.oanda_profiles import load_oanda_profile
from src.config.strategy_config import build_strategies_from_config
from src.connectors.backtest_provider import fetch_historical_1m_candles
from src.risk.costs import TransactionCostModel
from src.risk.kill_switch import KillSwitch
from src.risk.position_registry import position_registry
from src.schemas.events import Exchange
from src.system import TradingSystem

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backtest_oanda")

SYMBOLS = ["XAUUSD=X", "EURUSD=X"]


async def run(days: int):
    logger.info(f"=== FX BACKTEST ({days} days, symbols={SYMBOLS}) ===")

    KillSwitch.reset_singleton()
    position_registry.reset_singleton()

    sync_bus = SyncEventBus()
    async_bus_module.event_bus = sync_bus

    system = TradingSystem(
        providers={"angel": None, "groww": None, "kite_client": None, "kite_broker": None}
    )
    system.execution._paper_trading = True

    system.market_intel.set_exchange(Exchange.FX)
    for sym in SYMBOLS:
        system.market_intel.add_instrument(sym)

    xau_config = load_oanda_profile("XAU_USD")
    eur_config = load_oanda_profile("EUR_USD")

    system.strategy_gen._load_default_strategies = lambda: None
    for sym, config in [("XAUUSD=X", xau_config), ("EURUSD=X", eur_config)]:
        strategies = build_strategies_from_config(config)
        for s in strategies.values():
            system.strategy_gen.register_strategy(s)

    logger.info(
        "Registered FX strategies: %s",
        list(system.strategy_gen._strategies.keys()),
    )

    for agent in system._agents:
        original_start = agent.start

        async def patched_start(orig=original_start):
            return await orig(run_background_loop=False)

        agent.start = patched_start

    orig_handle_risk_check = system.execution._handle_risk_check

    async def patched_handle_risk_check(event):
        if event.data.get("check_name") == "order_validation" and event.data.get("passed"):
            order_data = event.data.get("details", {}).get("order", {})
            if order_data:
                await system.execution._submit_approved_order(
                    order_data, correlation_id=event.metadata.correlation_id
                )
                return
        await orig_handle_risk_check(event)

    system.execution._handle_risk_check = patched_handle_risk_check

    await system.start()

    for agent in system._agents:
        sync_bus.register_agent(agent)

    total_candles = 0
    for sym in SYMBOLS:
        candles = await fetch_historical_1m_candles(sym, exchange="FX", days=days)
        logger.info(f"Fetched {len(candles)} candles for {sym}")
        total_candles += len(candles)

        for c in candles:
            ts = c.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    ts = None
            await system.inject_ohlcv(
                instrument=sym,
                interval="minute",
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                volume=c.get("volume", 0),
                exchange="FX",
                timestamp=ts or datetime.now(UTC),
            )

    all_positions = position_registry.get_all_positions()
    open_positions = {k: v for k, v in all_positions.items() if abs(v.get("quantity", 0)) > 0}
    po = system.portfolio_opt
    cost_model = TransactionCostModel()

    if open_positions:
        logger.info(f"Closing {len(open_positions)} open position(s)...")
        for inst, pos in open_positions.items():
            qty = pos["quantity"]
            if qty == 0:
                continue
            side = "sell" if qty > 0 else "buy"
            price = pos.get("avg_price", 0.0)
            if price <= 0:
                continue
            txn_fee = cost_model.total_cost(side, abs(qty), price, product="mis")

            if side == "sell":
                realized_pnl = (price - pos["avg_price"]) * abs(qty)
                po._pnl += realized_pnl
                po._capital += (price * abs(qty)) - txn_fee
            else:
                po._capital -= (price * abs(qty)) + txn_fee

            await position_registry.update_from_fill(inst, side, abs(qty), price)
            logger.info(
                "Closed %s %d @ %.2f (PnL: %.2f)",
                inst, abs(qty), price,
                realized_pnl if side == "sell" else 0.0,
            )

    await system.stop()

    logger.info("=== BACKTEST COMPLETE ===")
    logger.info(f"Total Candles Processed: {total_candles}")

    fills = system.execution._filled_orders
    total_fills = sum(len(f) for f in fills.values())
    logger.info(f"Total Trade Fills: {total_fills}")

    buy_count = sell_count = 0
    for fills_list in fills.values():
        for fill in fills_list:
            side = getattr(fill, "side", None)
            side_val = side.value if hasattr(side, "value") else str(side)
            if side_val.lower() in ("buy", "long"):
                buy_count += 1
            else:
                sell_count += 1
    logger.info(f"  Buys: {buy_count}  Sells: {sell_count}")

    if po:
        logger.info(f"PnL            : {po._pnl:,.2f}")
        logger.info(f"Capital        : {po._capital:,.2f}")
        logger.info(f"Peak Capital   : {po._peak_capital:,.2f}")
        return_pct = ((po._capital - 1_000_000) / 1_000_000) * 100 if po._capital else 0.0
        logger.info(f"Return         : {return_pct:.2f}%")
        open_pos = (
            po._count_open_positions()
            if hasattr(po, "_count_open_positions")
            else len(position_registry.get_all_positions())
        )
        logger.info(f"Open Positions : {open_pos}")

    print("\n=== POSITIONS SUMMARY ===")
    for sym in SYMBOLS:
        pos = position_registry.get_position(sym)
        print(f"{sym}: qty={pos['quantity']}, unrealized_pnl={pos.get('unrealized_pnl', 0):.2f}")
    print(f"Symbols tested: {SYMBOLS}")
    print(f"Days: {days}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FX Backtest for OANDA instruments")
    parser.add_argument("--days", type=int, default=30, help="Number of days of historical data")
    args = parser.parse_args()
    asyncio.run(run(args.days))
