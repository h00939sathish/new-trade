#!/usr/bin/env python3
"""
Full pipeline demo: Market Data → Strategy → Risk → Execution

Injects simulated NSE stock ticks, runs through all 4 agents,
and prints the event flow in real-time.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from src.system import TradingSystem


async def print_events(system: TradingSystem, label: str):
    store = system.market_intel.event_store
    last_pos = 0
    while True:
        try:
            streams = await store.get_stream_names()
            for stream in streams:
                events = await store.read(stream, offset=last_pos, limit=50)
                for e in events:
                    ts = e.timestamp.strftime("%H:%M:%S.%f")[:12]
                    print(f"  [{ts}] {e.event_type.value:25s} {e.stream}")
                    if e.event_type.value == "signal.generated":
                        d = e.data
                        print(
                            f"         → {d.get('direction', '?')}:{d.get('confidence', 0):.2f} [{d.get('strategy', '?')}]"
                        )
                    if e.event_type.value in ("order.fill", "order.created"):
                        d = e.data
                        print(
                            f"         → {d.get('side', '?')} {d.get('quantity', 0)} @ {d.get('fill_price', d.get('price', 0))}"
                        )
                    if e.event_type.value == "risk.breach":
                        print(f"         ⚠ BLOCKED: {e.data.get('check_name', '?')}")
                    if e.position:
                        last_pos = max(last_pos, e.position)
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def main():
    print("=" * 60)
    print("TRADING SYSTEM — Full Pipeline Demo")
    print("=" * 60)

    system = TradingSystem()
    viewer = asyncio.create_task(print_events(system, "flow"))

    await system.start()
    print("\n✅ All agents started")
    print("   Subscriptions:")
    for agent in [system.market_intel, system.strategy_gen, system.risk_mgmt, system.execution]:
        print(f"   {agent.name}: {agent._stream_patterns}")

    print("\n📊 Injecting simulated market data...\n")

    scissors = [
        ("RELIANCE", 2510),
        ("TCS", 3450),
        ("INFY", 1580),
        ("HDFCBANK", 1620),
        ("ICICIBANK", 1050),
    ]

    for symbol, base_price in scissors:
        for offset in range(25):
            price = base_price + offset
            await system.inject_tick(symbol, price, volume=5000 + offset * 100)
            await asyncio.sleep(0.02)

    print("\n⏳ Waiting for pipeline to process...")
    await asyncio.sleep(3.0)

    print("\n📈 Event replay summary:\n")
    store = system.market_intel.event_store
    counts: dict[str, int] = {}
    async for event in store.replay():
        t = event.event_type.value
        counts[t] = counts.get(t, 0) + 1

    for etype, count in sorted(counts.items()):
        print(f"   {etype:30s}: {count:3d}")
    print(f"\n   {'TOTAL':30s}: {sum(counts.values()):3d}")

    print("\n📊 Agent health:\n")
    health = await system.health()
    for name, status in health.items():
        print(
            f"   {name}: {status['status']} | "
            f"patterns: {len(status['patterns'])} | "
            f"streams: {len(status['resolved_streams'])}"
        )

    await system.stop()
    viewer.cancel()

    print("\n" + "=" * 60)
    print("Demo complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
