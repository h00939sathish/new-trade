import asyncio
import os

db = "trading_events.db"
if os.path.exists(db):
    os.remove(db)

from src.system import TradingSystem

process_tick_count = 0

class DebugTradingSystem(TradingSystem):
    pass

async def main():
    global process_tick_count

    system = TradingSystem()
    await system.start()
    await asyncio.sleep(0.3)

    for price in [100.0]*15 + [105.0, 110.0, 115.0, 120.0, 125.0, 130.0]:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await asyncio.sleep(0.02)

    await asyncio.sleep(2.0)

    # Count events in store
    total = 0
    tick_events = 0
    async for e in system._event_store.replay():
        total += 1
        if e.event_type.value == "market.tick":
            tick_events += 1
    print("Total events in store: %d" % total)
    print("Tick events in store: %d" % tick_events)

    ph = system.strategy_gen._price_history.get("RELIANCE", [])
    print("Price history length: %d" % len(ph))
    print(f"First 5: {list(ph)[:5]}")
    print(f"Last 5: {list(ph)[-5:]}")

    # Verify individual tick data
    async for e in system._event_store.replay():
        if e.event_type.value == "market.tick":
            lp = e.data.get("last_price")
            if lp is None:
                print(f"WARNING: tick has no last_price! data={e.data}")
            break

    await system.stop()

asyncio.run(main())
