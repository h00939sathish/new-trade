from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy


@pytest.mark.asyncio
async def test_orb_strategy_long_signal():
    strategy = OpeningRangeBreakoutStrategy()
    ist = ZoneInfo("Asia/Kolkata")

    timestamps = []
    prices = []
    highs = []
    lows = []
    volumes = []

    # 200 previous days for EMA200
    date(2026, 6, 1)

    # Fill 200 candles before today to satisfy EMA200
    for i in range(200):
        ts = datetime(2026, 5, 1, 10, 0, tzinfo=ist)
        timestamps.append(ts)
        prices.append(100.0)
        highs.append(102.0)
        lows.append(98.0)
        volumes.append(1000)

    # Now add today's opening range candles (09:15 - 09:30)
    for m in range(15, 30):
        ts = datetime(2026, 6, 1, 9, m, tzinfo=ist)
        timestamps.append(ts)
        prices.append(105.0)
        highs.append(105.0)  # OR high = 105.0
        lows.append(104.0)  # OR low = 104.0
        volumes.append(1500)

    # Now current time is 09:45, price breaks above 105.0 -> 106.0
    ts = datetime(2026, 6, 1, 9, 45, tzinfo=ist)
    timestamps.append(ts)
    prices.append(106.0)
    highs.append(106.0)
    lows.append(105.0)
    volumes.append(2000)  # Volume filter > 1.2 * avg

    signal = await strategy.evaluate(
        instrument="RELIANCE",
        prices=prices,
        volumes=volumes,
        highs=highs,
        lows=lows,
        timestamps=timestamps,
    )

    assert signal is not None
    assert signal["direction"] == "long"
    assert "sl_pct_override" in signal["features"]
    assert "tp_pct_override" in signal["features"]
