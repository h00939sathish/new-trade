import asyncio
import os

db = "trading_events.db"
if os.path.exists(db):
    os.remove(db)

from src.system import TradingSystem

call_count = 0
original_process_tick = None

async def main():
    global call_count

    system = TradingSystem()

    # Monkey-patch to count calls
    sg = system.strategy_gen
    orig_on_event = sg.on_event

    async def counting_on_event(event):
        global call_count
        if event.event_type.value == "market.tick":
            call_count += 1
        await orig_on_event(event)

    sg.on_event = counting_on_event

    await system.start()
    await asyncio.sleep(0.3)

    for price in [100.0]*15 + [105.0, 110.0, 115.0, 120.0, 125.0, 130.0]:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await asyncio.sleep(0.02)

    await asyncio.sleep(2.0)

    ph = system.strategy_gen._price_history.get("RELIANCE", [])
    print("on_event tick calls: %d" % call_count)
    print("Price history length: %d" % len(ph))
    print(f"Prices: {list(ph)}")

    await system.stop()

asyncio.run(main())
