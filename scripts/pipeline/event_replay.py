#!/usr/bin/env python3
import json
import logging
import sys
import threading
import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")


logger = logging.getLogger("pipeline.event_replay")

EVENTS_DIR = Path("events")
_WRITE_LOCK = threading.Lock()


def _date_path(dt: date) -> Path:
    return EVENTS_DIR / dt.strftime("%Y-%m-%d") / "events.jsonl"


def ensure_dir() -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def store_event(event_dict: dict[str, Any]) -> Path:
    ensure_dir()

    ts = event_dict.get("timestamp")
    if ts is None:
        ts = datetime.now(UTC)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if isinstance(ts, datetime):
        event_date = ts.date()
    else:
        event_date = date.today()

    event_dict.setdefault("event_id", uuid.uuid4().hex)
    event_dict.setdefault("timestamp", datetime.now(UTC).isoformat())
    event_dict.setdefault("strategy_id", None)
    event_dict.setdefault("correlation_id", uuid.uuid4().hex)
    event_dict.setdefault("symbol", None)
    event_dict.setdefault("data", {})

    path = _date_path(event_date)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(event_dict, default=str)

    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    logger.debug("Stored event %s -> %s", event_dict["event_id"], path)
    return path


def replay_events(
    date_from: date | str,
    date_to: date | str,
    event_types: list[str] | None = None,
) -> Generator[dict[str, Any], None, None]:
    if isinstance(date_from, str):
        date_from = date.fromisoformat(date_from)
    if isinstance(date_to, str):
        date_to = date.fromisoformat(date_to)

    if not EVENTS_DIR.exists():
        return

    current = date_from
    while current <= date_to:
        path = _date_path(current)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed event line in %s", path)
                        continue

                    if event_types and event.get("event_type") not in event_types:
                        continue

                    yield event

        current += timedelta(days=1)


def get_available_dates() -> list[date]:
    if not EVENTS_DIR.exists():
        return []

    dates: list[date] = []
    for entry in sorted(EVENTS_DIR.iterdir()):
        if entry.is_dir():
            try:
                dates.append(date.fromisoformat(entry.name))
            except ValueError:
                continue
    return sorted(dates)


def count_events(
    date_from: date | str,
    date_to: date | str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in replay_events(date_from, date_to):
        et = event.get("event_type", "unknown")
        counts[et] = counts.get(et, 0) + 1
    return counts


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    import argparse

    parser = argparse.ArgumentParser(description="Event store and replay utility")
    sub = parser.add_subparsers(dest="command")

    store_cmd = sub.add_parser("store", help="Store an event")
    store_cmd.add_argument("--type", required=True, help="Event type")
    store_cmd.add_argument("--symbol", default=None, help="Symbol")
    store_cmd.add_argument("--strategy", default=None, dest="strategy_id", help="Strategy ID")
    store_cmd.add_argument("--data", default="{}", help="JSON data")

    replay_cmd = sub.add_parser("replay", help="Replay events")
    replay_cmd.add_argument("--from", dest="date_from", required=True, help="From date YYYY-MM-DD")
    replay_cmd.add_argument("--to", dest="date_to", required=True, help="To date YYYY-MM-DD")
    replay_cmd.add_argument("--types", nargs="*", help="Event type filter")

    count_cmd = sub.add_parser("count", help="Count events")
    count_cmd.add_argument("--from", dest="date_from", required=True, help="From date YYYY-MM-DD")
    count_cmd.add_argument("--to", dest="date_to", required=True, help="To date YYYY-MM-DD")

    sub.add_parser("dates", help="List available dates")

    args = parser.parse_args()

    if args.command == "store":
        import ast
        data_dict = ast.literal_eval(args.data) if isinstance(args.data, str) else {}
        event = {
            "event_type": args.type,
            "symbol": args.symbol,
            "strategy_id": args.strategy_id,
            "data": data_dict,
        }
        path = store_event(event)
        print(f"Stored event -> {path}")

    elif args.command == "replay":
        count = 0
        for event in replay_events(args.date_from, args.date_to, args.types):
            print(json.dumps(event, default=str))
            count += 1
        print(f"\nReplayed {count} events", file=sys.stderr)

    elif args.command == "count":
        counts = count_events(args.date_from, args.date_to)
        total = 0
        for etype, cnt in sorted(counts.items()):
            print(f"{etype:30s}: {cnt}")
            total += cnt
        print(f"{'TOTAL':30s}: {total}")

    elif args.command == "dates":
        for d in get_available_dates():
            print(d.isoformat())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
