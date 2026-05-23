from datetime import datetime

import pytest

from src.schemas.events import Exchange
from src.utils.timeframe import aggregate_candles, round_timestamp, timeframe_to_minutes


class TestTimeframeUtils:
    def test_timeframe_to_minutes_minute(self):
        assert timeframe_to_minutes("minute") == 1

    def test_timeframe_to_minutes_5minute(self):
        assert timeframe_to_minutes("5minute") == 5

    def test_timeframe_to_minutes_60minute(self):
        assert timeframe_to_minutes("60minute") == 60

    def test_timeframe_to_minutes_day(self):
        assert timeframe_to_minutes("day") == 1440

    def test_round_timestamp_five_minute(self):
        dt = datetime(2024, 1, 15, 10, 23, 45)
        rounded = round_timestamp(dt, 5)
        assert rounded.minute == 20
        assert rounded.second == 0

    def test_round_timestamp_hour(self):
        dt = datetime(2024, 1, 15, 10, 45, 0)
        rounded = round_timestamp(dt, 60)
        assert rounded.minute == 0
        assert rounded.hour == 10

    def test_round_timestamp_day(self):
        dt = datetime(2024, 1, 15, 10, 23, 45)
        rounded = round_timestamp(dt, 1440)
        assert rounded.hour == 0
        assert rounded.minute == 0


class TestAggregateCandles:
    def test_aggregate_empty_candles(self):
        result = aggregate_candles("minute", [])
        assert result == {}

    def test_aggregate_single_candle(self):
        candles = [{"timestamp": "2024-01-15T10:00:00", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000}]
        result = aggregate_candles("minute", candles)
        assert "5minute" in result
        assert len(result["5minute"]) == 1
        assert result["5minute"][0]["open"] == 100
        assert result["5minute"][0]["close"] == 104

    def test_aggregate_5_minute_from_1_minute(self):
        candles = []
        for i in range(5):
            ts = f"2024-01-15T10:0{i}:00"
            candles.append({"timestamp": ts, "open": 100 + i, "high": 105 + i, "low": 99 + i, "close": 104 + i, "volume": 100})
        result = aggregate_candles("minute", candles)
        assert len(result["5minute"]) == 1
        c = result["5minute"][0]
        assert c["open"] == 100
        assert c["close"] == 108
        assert c["high"] == 109
        assert c["low"] == 99
        assert c["volume"] == 500

    def test_aggregate_ignores_equal_or_lower(self):
        candles = [{"timestamp": "2024-01-15T10:00:00", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000}]
        result = aggregate_candles("5minute", candles)
        assert "5minute" not in result
        assert "minute" not in result

    def test_aggregate_sorts_by_timestamp(self):
        candles = [
            {"timestamp": "2024-01-15T10:05:00", "open": 110, "high": 115, "low": 109, "close": 114, "volume": 100},
            {"timestamp": "2024-01-15T10:00:00", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 100},
        ]
        result = aggregate_candles("minute", candles)
        c = result["5minute"]
        assert len(c) >= 1
        assert c[0]["timestamp"] <= c[-1]["timestamp"]


@pytest.mark.asyncio
async def test_market_intel_aggregation():
    from src.agents.market_intel import MarketIntelAgent
    src_interval = "minute"

    agent = MarketIntelAgent(event_store=None)
    await agent.start()

    for i in range(5):
        close = 100.0 + i
        await agent.ingest_ohlcv(
            instrument="TEST",
            exchange=Exchange.NSE,
            interval=src_interval,
            open=close - 0.5,
            high=close + 0.25,
            low=close - 0.5,
            close=close,
            volume=1000,
        )

    assert len(agent._candle_buffer[f"TEST.{src_interval}"]) >= 5
    await agent.stop()

