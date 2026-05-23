import asyncio
import logging
import os

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

db = "trading_events.db"
if os.path.exists(db):
    os.remove(db)

from src.system import TradingSystem


async def main():
    system = TradingSystem()
    await system.start()
    await asyncio.sleep(0.3)

    for price in [100.0]*15 + [105.0, 110.0, 115.0, 120.0, 125.0, 130.0]:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await asyncio.sleep(0.02)

    await asyncio.sleep(2.0)

    ph = system.strategy_gen._price_history.get("RELIANCE", [])
    print("\n=== RESULTS ===")
    print("Price history length: %d" % len(ph))
    print(f"Prices: {list(ph)}")

    signals = []
    async for e in system._event_store.replay():
        if e.event_type.value == "signal.generated":
            signals.append(e)
    print("Signals: %d" % len(signals))
    for s in signals:
        print(f"  {s.data}")

    await system.stop()

asyncio.run(main())
