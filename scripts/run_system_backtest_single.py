import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Insert src into path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.event_store.async_bus as async_bus_module
from src.backtest.sync_bus import SyncEventBus
from src.connectors.backtest_provider import BacktestDataProvider
from src.system import TradingSystem

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("system_backtest")


async def run(days: int):
    logger.info(f"=== FULL SYSTEM BACKTEST ({days} days) ===")

    # Reset KillSwitch singleton so stale state from prior runs doesn't block signals
    from src.risk.kill_switch import KillSwitch
    KillSwitch.reset_singleton()

    # 1. Replace the global AsyncEventBus with our SyncEventBus
    sync_bus = SyncEventBus()
    async_bus_module.event_bus = sync_bus

    # 2. Instantiate System without real broker
    system = TradingSystem(
        providers={"angel": None, "groww": None, "kite_client": None, "kite_broker": None}
    )
    system.execution._paper_trading = True

    # Set watchlist from environment or fallback
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    env_watchlist = os.getenv("TRA_WATCHLIST")
    if env_watchlist:
        watchlist = env_watchlist.split(",")
    else:
        watchlist = ["RELIANCE", "TCS", "HDFCBANK", "INFY"]

    logger.info(f"Using watchlist: {watchlist}")
    system.set_watchlist(watchlist)

    # Override strategy_gen thresholds for minute-data backtest
    system.strategy_gen.threshold = 0.01
    system.strategy_gen.short_threshold = 0.01

    # 3. Patch agents to prevent their background loops
    for agent in system._agents:
        original_start = agent.start

        async def patched_start(orig=original_start):
            return await orig(run_background_loop=False)

        agent.start = patched_start

    # 4. Patch execution to call _submit_approved_order directly (no create_task)
    #    In the backtest context, asyncio.create_task never runs because there's
    #    no yield point between task creation and tick completion.
    orig_handle_risk_check = system.execution._handle_risk_check

    async def patched_handle_risk_check(event):
        # If it's an order_validation with a passed check, call the submit directly
        if event.data.get("check_name") == "order_validation" and event.data.get("passed"):
            order_data = event.data.get("details", {}).get("order", {})
            if order_data:
                await system.execution._submit_approved_order(
                    order_data, correlation_id=event.metadata.correlation_id
                )
                return
        # Otherwise delegate to original
        await orig_handle_risk_check(event)

    system.execution._handle_risk_check = patched_handle_risk_check

    # 5. Start system — this calls each agent's on_start(), which sets up subscriptions
    await system.start()

    # 7. Register agents on SyncEventBus after start
    for agent in system._agents:
        sync_bus.register_agent(agent)

    # 8. Fetch Historical Data
    logger.info(f"Fetching {days} days of historical data for {watchlist}...")
    provider = BacktestDataProvider(market_data_provider=None, instruments=watchlist)
    ticks = await provider.get_backtest_ticks(days=days)

    if not ticks:
        logger.error("No historical ticks found!")
        return

    logger.info(f"Loaded {len(ticks)} total ticks. Beginning tick-by-tick simulation...")

    # 9. Run simulation tick-by-tick synchronously
    ticks_processed = 0
    for tick in ticks:
        instrument = tick.get("instrument")
        price = tick.get("price") or tick.get("last_price")
        if not instrument or not price:
            continue

        await system.inject_ohlcv(
            instrument=instrument,
            interval="minute",
            open=tick.get("open", price),
            high=tick.get("high", price),
            low=tick.get("low", price),
            close=price,
            volume=tick.get("volume", 0),
            exchange="NSE",
            timestamp=tick.get("timestamp"),
        )
        ticks_processed += 1
        if ticks_processed % 10000 == 0:
            logger.info(f"Processed {ticks_processed} / {len(ticks)} ticks...")

    # 10. Inject a test signal to verify end-to-end pipeline (signal → fill → PnL)
    from src.schemas.events import Exchange, SignalEvent

    test_signal = SignalEvent.create(
        instrument=watchlist[0],
        exchange=Exchange.NSE,
        direction="long",
        confidence=0.7,
        price=2500.0,
        strategy="backtest_verification",
        producer="system_backtest",
    )
    await sync_bus.publish(test_signal)
    logger.info("Test signal injected for %s — verifying pipeline...", watchlist[0])

    # 11. Close open positions (directly, without triggering strategy cascade)
    from src.risk.position_registry import position_registry
    from src.schemas.events import OrderSide
    from src.risk.costs import TransactionCostModel

    all_positions = position_registry.get_all_positions()
    open_positions = {k: v for k, v in all_positions.items() if abs(v.get("quantity", 0)) > 0}
    po = system.portfolio_opt
    cost_model = TransactionCostModel()

    if open_positions:
        logger.info(f"Closing {len(open_positions)} open position(s) for PnL realization...")
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
                "Closed %s %d @ %.2f (PnL: %.2f)", inst, abs(qty), price,
                realized_pnl if side == "sell" else 0.0,
            )

    # 11. Stop system (clean, no positions to close → no cascade)
    await system.stop()

    # 12. Print Performance Results
    logger.info("=== SIMULATION COMPLETE ===")
    logger.info(f"Total Ticks Processed: {ticks_processed}")

    fills = system.execution._filled_orders
    total_fills = sum(len(f) for f in fills.values())
    logger.info(f"Total Trade Fills Generated: {total_fills}")

    # Count buys vs sells for context
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
        return_pct = ((po._capital - 1_000_000) / 1_000_000) * 100
        logger.info(f"Return         : {return_pct:.2f}%")
        logger.info(f"Open Positions : {po._count_open_positions()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.days))
