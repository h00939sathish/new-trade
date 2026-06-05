"""
Tests for P2.2 — per-strategy attribution aggregator.
"""
import pytest

from src.analytics.attribution import AttributionAggregator


def _fill(side, qty, price, strategy="momentum", timestamp="2026-06-05T10:00:00"):
    return {
        "side": side,
        "fill_quantity": qty,
        "fill_price": price,
        "strategy": strategy,
        "timestamp": timestamp,
    }


def test_no_fills_empty_summary():
    agg = AttributionAggregator()
    summary = agg.get_summary()
    assert summary == {}


def test_single_buy_no_pnl():
    agg = AttributionAggregator()
    agg.add_fill(_fill("buy", 10, 100.0))
    summary = agg.get_summary()
    assert summary["momentum"]["trades"] == 0  # no sell = no closed trade
    assert summary["momentum"]["total_pnl"] == 0.0
    assert summary["momentum"]["fills"] == 1


def test_round_trip_winning():
    """Buy 10 @ 100, sell 10 @ 110 → PnL = 100, win."""
    agg = AttributionAggregator()
    agg.add_fill(_fill("buy", 10, 100.0))
    agg.add_fill(_fill("sell", 10, 110.0))
    summary = agg.get_summary()
    s = summary["momentum"]
    assert s["trades"] == 1
    assert s["wins"] == 1
    assert s["losses"] == 0
    assert s["total_pnl"] == 100.0
    assert s["expectancy"] == 100.0
    assert s["win_rate"] == 1.0
    assert s["profit_factor"] is None  # no losses → inf → serialized as None


def test_round_trip_losing():
    """Buy 10 @ 100, sell 10 @ 90 → PnL = -100, loss."""
    agg = AttributionAggregator()
    agg.add_fill(_fill("buy", 10, 100.0))
    agg.add_fill(_fill("sell", 10, 90.0))
    summary = agg.get_summary()
    s = summary["momentum"]
    assert s["trades"] == 1
    assert s["wins"] == 0
    assert s["losses"] == 1
    assert s["total_pnl"] == -100.0
    assert s["expectancy"] == -100.0
    assert s["profit_factor"] == 0.0  # no wins


def test_per_strategy_segregation():
    """Two strategies, each with their own PnL."""
    agg = AttributionAggregator()
    agg.add_fill(_fill("buy", 10, 100.0, strategy="momentum"))
    agg.add_fill(_fill("sell", 10, 110.0, strategy="momentum"))
    agg.add_fill(_fill("buy", 5, 200.0, strategy="vwap_reversion"))
    agg.add_fill(_fill("sell", 5, 220.0, strategy="vwap_reversion"))
    summary = agg.get_summary()
    assert summary["momentum"]["total_pnl"] == 100.0
    assert summary["vwap_reversion"]["total_pnl"] == 100.0


def test_signal_counting():
    """add_signal increments the signal count for a strategy."""
    agg = AttributionAggregator()
    agg.add_signal("momentum")
    agg.add_signal("momentum")
    agg.add_signal("vwap_reversion")
    summary = agg.get_summary()
    assert summary["momentum"]["signals"] == 2
    assert summary["vwap_reversion"]["signals"] == 1


def test_sharpe_ratio_with_enough_trades():
    """Sharpe is 0 with <5 trades, computed with ≥5."""
    agg = AttributionAggregator()
    # 6 round-trips, all winning
    for i in range(6):
        agg.add_fill(_fill("buy", 10, 100.0))
        agg.add_fill(_fill("sell", 10, 100.0 + (i + 1) * 5))
    summary = agg.get_summary()
    s = summary["momentum"]
    assert s["trades"] == 6
    assert s["sharpe_20"] != 0.0  # at least 5 trades → sharpe computed


def test_daily_report_writes_to_jsonl(tmp_path):
    """write_daily_report produces a JSONL line with the summary."""
    agg = AttributionAggregator()
    agg.add_fill(_fill("buy", 10, 100.0))
    agg.add_fill(_fill("sell", 10, 110.0))
    path = agg.write_daily_report(out_dir=tmp_path)
    assert path.exists()
    content = path.read_text()
    assert "per_strategy" in content
    assert "momentum" in content
    # Each invocation appends; should be ≥1 line
    assert content.count("\n") >= 1


def test_load_from_db_when_db_missing():
    """load_from_db should not crash if the DB file doesn't exist."""
    agg = AttributionAggregator(db_path="/nonexistent/path/db.sqlite")
    agg.load_from_db()  # should log warning, not raise
    assert agg.get_summary() == {}
