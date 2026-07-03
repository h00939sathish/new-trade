import pytest
from datetime import UTC, datetime, timedelta

from src.strategies.m15_trend import M15TrendConfirmation, _round_to_m15


class TestM15TrendConfirmation:
    def test_not_warmed_initially(self):
        c = M15TrendConfirmation()
        assert not c.is_warmed()
        assert c.get_regime() is None

    def test_rejects_single_candle(self):
        c = M15TrendConfirmation()
        c.update({
            "open": 2350,
            "high": 2351,
            "low": 2349,
            "close": 2350.5,
            "volume": 100,
            "timestamp": datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC),
        })
        assert not c.is_warmed()

    def test_warms_after_sufficient_candles(self):
        c = M15TrendConfirmation()
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(300):
            price = 2350 + (i % 20) * 0.5
            c.update({
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.2,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        assert c.is_warmed()

    def test_aggregates_correct_m15_boundary(self):
        c = M15TrendConfirmation()
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(15):
            c.update({
                "open": 2350.0 + i * 0.1,
                "high": 2351.0 + i * 0.1,
                "low": 2349.0 + i * 0.1,
                "close": 2350.5 + i * 0.1,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        assert len(c._m15_bars) == 1

    def test_m15_boundary_split(self):
        c = M15TrendConfirmation()
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(16):
            c.update({
                "open": 2350.0,
                "high": 2351.0,
                "low": 2349.0,
                "close": 2350.5,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        assert len(c._m15_bars) == 2

    def test_out_of_order_candle_creates_new_bar(self):
        c = M15TrendConfirmation()
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        c.update({
            "open": 2350, "high": 2351, "low": 2349, "close": 2350.5,
            "volume": 100, "timestamp": base + timedelta(minutes=30),
        })
        c.update({
            "open": 2340, "high": 2345, "low": 2338, "close": 2342,
            "volume": 100, "timestamp": base + timedelta(minutes=0),
        })
        # out-of-order lands in a different M15 bucket -> new bar appended
        assert len(c._m15_bars) == 2

    def test_duplicate_timestamp_updates_same_bar(self):
        c = M15TrendConfirmation()
        ts = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        c.update({
            "open": 2350, "high": 2351, "low": 2349, "close": 2350.5,
            "volume": 100, "timestamp": ts,
        })
        c.update({
            "open": 2350, "high": 2352, "low": 2348, "close": 2351,
            "volume": 50, "timestamp": ts,
        })
        assert len(c._m15_bars) == 1
        bar = c._m15_bars[-1]
        assert bar["high"] == 2352
        assert bar["low"] == 2348
        assert bar["close"] == 2351
        assert bar["volume"] == 150

    def test_trending_up_regime(self):
        c = M15TrendConfirmation(ema_period=5, adx_period=5)
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        # Rising prices across many M15 buckets -> close > EMA, ADX > 25
        for i in range(200):
            price = 2350 + i * 0.5
            c.update({
                "open": price,
                "high": price + 1,
                "low": price - 0.5,
                "close": price + 0.5,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        regime = c.get_regime()
        assert regime == "trending_up", f"Expected trending_up, got {regime}"

    def test_trending_down_regime(self):
        c = M15TrendConfirmation(ema_period=5, adx_period=5)
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(200):
            price = 2500 - i * 0.5
            c.update({
                "open": price,
                "high": price + 0.5,
                "low": price - 1,
                "close": price - 0.5,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        regime = c.get_regime()
        assert regime == "trending_down", f"Expected trending_down, got {regime}"

    def test_ranging_regime(self):
        c = M15TrendConfirmation(ema_period=5, adx_period=5)
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(200):
            price = 2350 + (i % 3) * 0.1  # sideways chop
            c.update({
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price + 0.05,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        regime = c.get_regime()
        assert regime == "ranging", f"Expected ranging, got {regime}"

    def test_confirms_buy_on_trending_up(self):
        c = M15TrendConfirmation(ema_period=5, adx_period=5)
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(200):
            price = 2350 + i * 0.5
            c.update({
                "open": price,
                "high": price + 1,
                "low": price - 0.5,
                "close": price + 0.5,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        assert c.confirms("buy")
        assert not c.confirms("sell")

    def test_confirms_sell_on_trending_down(self):
        c = M15TrendConfirmation(ema_period=5, adx_period=5)
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(200):
            price = 2500 - i * 0.5
            c.update({
                "open": price,
                "high": price + 0.5,
                "low": price - 1,
                "close": price - 0.5,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        assert c.confirms("sell")
        assert not c.confirms("buy")

    def test_confirms_returns_false_when_not_warmed(self):
        c = M15TrendConfirmation()
        assert not c.confirms("buy")
        assert not c.confirms("sell")

    def test_round_to_m15(self):
        dt = datetime(2026, 7, 1, 12, 7, 0, tzinfo=UTC)
        assert _round_to_m15(dt).minute == 0
        dt = datetime(2026, 7, 1, 12, 15, 0, tzinfo=UTC)
        assert _round_to_m15(dt).minute == 15
        dt = datetime(2026, 7, 1, 12, 44, 59, tzinfo=UTC)
        assert _round_to_m15(dt).minute == 30
        dt = datetime(2026, 7, 1, 12, 45, 0, tzinfo=UTC)
        assert _round_to_m15(dt).minute == 45

    def test_handles_string_timestamp(self):
        c = M15TrendConfirmation()
        c.update({
            "open": 2350, "high": 2351, "low": 2349, "close": 2350.5,
            "volume": 100,
            "timestamp": "2026-07-01T00:00:00Z",
        })
        assert len(c._m15_bars) == 1

    def test_get_regime_returns_none_when_not_warmed(self):
        c = M15TrendConfirmation()
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        for i in range(10):
            c.update({
                "open": 2350, "high": 2351, "low": 2349, "close": 2350.5,
                "volume": 100,
                "timestamp": base + timedelta(minutes=i),
            })
        assert c.get_regime() is None
