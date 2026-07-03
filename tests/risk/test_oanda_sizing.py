import pytest

from src.risk.oanda_sizing import (
    RISK_PER_TRADE,
    MAX_COMBINED_RISK,
    calculate_oanda_units,
    validate_oanda_order,
)


class TestOandaSizing:
    def test_calculate_units_basic(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        units = calculate_oanda_units(
            equity_usd=10000.0,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
        )
        assert units == 2

    def test_calculate_units_below_minimum(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        units = calculate_oanda_units(
            equity_usd=1000.0,
            entry_price=2350.0,
            stop_price=2300.0,
            instrument_meta=meta,
        )
        assert units == 0

    def test_validate_oanda_order_accepts(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=2,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
            combined_risk=0.004,
        )
        assert ok is True

    def test_validate_oanda_order_rejects_excessive_combined_risk(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=10,
            entry_price=2350.0,
            stop_price=2000.0,
            instrument_meta=meta,
            combined_risk=0.015,
        )
        assert ok is False
        assert "combined" in reason.lower()

    def test_zero_stop_distance_returns_zero(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        units = calculate_oanda_units(
            equity_usd=10000.0,
            entry_price=2350.0,
            stop_price=2350.0,
            instrument_meta=meta,
        )
        assert units == 0

    def test_negative_prices_validation_rejects(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=2,
            entry_price=-2350.0,
            stop_price=-2330.0,
            instrument_meta=meta,
            combined_risk=0.004,
        )
        assert ok is False
        assert "invalid" in reason.lower()

    def test_precision_rounding(self):
        meta = {"trade_units_precision": 1, "minimum_trade_size": 1}
        units = calculate_oanda_units(
            equity_usd=10000.0,
            entry_price=2350.0,
            stop_price=2340.0,
            instrument_meta=meta,
        )
        # risk_budget=50, risk_per_unit=10, raw=5.0, floor to 1dp = 5.0
        assert units == 5

    def test_precision_rounding_fractional(self):
        meta = {"trade_units_precision": 1, "minimum_trade_size": 1}
        units = calculate_oanda_units(
            equity_usd=10000.0,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
        )
        # risk_budget=50, risk_per_unit=20, raw=2.5, floor to 1dp = 2.5 -> int(...) truncates to 2
        assert units == 2

    def test_validate_rejects_zero_units(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=0,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
            combined_risk=0.004,
        )
        assert ok is False

    def test_calculate_units_precision_2dp(self):
        meta = {"trade_units_precision": 2, "minimum_trade_size": 1}
        units = calculate_oanda_units(
            equity_usd=10000.0,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
        )
        # risk_budget=50, risk_per_unit=20, raw=2.5, floor to 2dp = 2.5 -> int(...) truncates to 2
        assert units == 2

    def test_validate_rejects_when_combined_plus_new_exceeds_max(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=5,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
            combined_risk=0.008,
        )
        # new_risk = (5 * 20) / 10000 = 0.01, combined_risk 0.008 + 0.01 = 0.018 > 0.01
        assert ok is False

    def test_validate_rejects_zero_stop_distance(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 1}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=2,
            entry_price=2350.0,
            stop_price=2350.0,
            instrument_meta=meta,
            combined_risk=0.004,
        )
        assert ok is False
        assert "differ" in reason.lower()

    def test_validate_rejects_below_min_size(self):
        meta = {"trade_units_precision": 0, "minimum_trade_size": 5}
        ok, reason = validate_oanda_order(
            equity_usd=10000.0,
            units=2,
            entry_price=2350.0,
            stop_price=2330.0,
            instrument_meta=meta,
            combined_risk=0.004,
        )
        assert ok is False
        assert "below minimum" in reason.lower()
