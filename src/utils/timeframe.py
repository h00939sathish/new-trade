from datetime import datetime
from typing import Any

HIGHER_TIMEFRAMES = {
    "5minute": 5,
    "15minute": 15,
    "30minute": 30,
    "60minute": 60,
    "day": 1440,
}


def timeframe_to_minutes(interval: str) -> int:
    if interval == "day":
        return 1440
    if interval == "minute" or interval == "1minute":
        return 1
    val = interval.replace("minute", "")
    return int(val)


def round_timestamp(dt: datetime, minutes: int) -> datetime:
    if minutes >= 1440:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    total = dt.hour * 60 + dt.minute
    rounded = (total // minutes) * minutes
    return dt.replace(hour=rounded // 60, minute=rounded % 60, second=0, microsecond=0)


def aggregate_candles(
    source_interval: str, candles: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    if not candles:
        return {}

    source_min = timeframe_to_minutes(source_interval)
    result: dict[str, list[dict[str, Any]]] = {}

    for tf, tf_min in HIGHER_TIMEFRAMES.items():
        if tf_min <= source_min:
            continue

        buckets: dict[int, dict[str, Any]] = {}
        for c in candles:
            ts = c["timestamp"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            bucket_key = int(round_timestamp(ts, tf_min).timestamp())

            if bucket_key not in buckets:
                buckets[bucket_key] = {
                    "timestamp": bucket_key,
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c.get("volume", 0),
                }
            else:
                b = buckets[bucket_key]
                b["high"] = max(b["high"], c["high"])
                b["low"] = min(b["low"], c["low"])
                b["close"] = c["close"]
                b["volume"] = b.get("volume", 0) + c.get("volume", 0)

        if buckets:
            result[tf] = sorted(buckets.values(), key=lambda x: x["timestamp"])

    return result
