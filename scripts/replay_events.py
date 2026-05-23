#!/usr/bin/env python3
"""Replay events from the event store.

Usage:
    python scripts/replay_events.py                    # Replay all events
    python scripts/replay_events.py --stream tick.NSE.RELIANCE  # Filter by stream
    python scripts/replay_events.py --days 7           # Last 7 days
    python scripts/replay_events.py --limit 100        # Max 100 events
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from src.event_store import create_event_store


async def replay_events(
    stream: str | None = None,
    days: int | None = None,
    limit: int = 1000,
) -> None:
    store = create_event_store()
    await store.connect()

    try:
        after = None
        if days is not None:
            after = datetime.now(UTC) - timedelta(days=days)

        print("Replaying events...")
        if stream:
            print(f"  Stream: {stream}")
        if after:
            print(f"  After: {after.isoformat()}")
        print(f"  Limit: {limit}")
        print("-" * 60)

        count = 0
        async for event in store.replay(stream=stream, after=after):
            if count >= limit:
                break
            print(f"[{event.position}] {event.timestamp.isoformat()} "
                  f"{event.event_type.value:20s} {event.stream}")
            count += 1

        print("-" * 60)
        print(f"Total events replayed: {count}")

        stream_names = await store.get_stream_names()
        print(f"\nAvailable streams ({len(stream_names)}):")
        for s in sorted(stream_names):
            length = await store.get_stream_length(s)
            print(f"  {s}: {length} events")

    finally:
        await store.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay events from event store")
    parser.add_argument("--stream", type=str, help="Filter by stream name")
    parser.add_argument("--days", type=int, help="Events from last N days")
    parser.add_argument("--limit", type=int, default=1000, help="Max events (default: 1000)")
    args = parser.parse_args()

    asyncio.run(replay_events(
        stream=args.stream,
        days=args.days,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
