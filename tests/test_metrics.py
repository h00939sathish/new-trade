import pytest

from src.monitoring.metrics import MetricsCollector


class TestMetricsCollector:
    def test_snapshot_empty(self):
        m = MetricsCollector()
        snap = m.snapshot()
        assert snap["total_events"] == 0
        assert snap["uptime_seconds"] >= 0
        assert snap["event_rate"] == 0

    def test_count_events(self):
        m = MetricsCollector()
        m.count_event("market.tick")
        m.count_event("market.tick")
        m.count_event("signal.generated")
        snap = m.snapshot()
        assert snap["events_by_type"]["market.tick"] == 2
        assert snap["events_by_type"]["signal.generated"] == 1

    def test_count_signals(self):
        m = MetricsCollector()
        m.count_signal("momentum", "long")
        m.count_signal("momentum", "long")
        m.count_signal("rsi", "short")
        snap = m.snapshot()
        assert snap["signals_by_strategy"]["momentum:long"] == 2
        assert snap["signals_by_strategy"]["rsi:short"] == 1

    def test_count_orders(self):
        m = MetricsCollector()
        m.count_order("accepted")
        m.count_order("filled")
        m.count_order("rejected")
        snap = m.snapshot()
        assert snap["orders_by_status"]["accepted"] == 1

    def test_count_errors(self):
        m = MetricsCollector()
        m.count_error("market_intel")
        m.count_error("execution")
        snap = m.snapshot()
        assert "market_intel" in snap["errors_by_component"]

    def test_latency_recording(self):
        m = MetricsCollector()
        m.record_latency(0.05)
        m.record_latency(0.10)
        snap = m.snapshot()
        assert snap["avg_latency_ms"] == pytest.approx(75.0)

    def test_prometheus_text(self):
        m = MetricsCollector()
        m.count_event("market.tick")
        m.count_signal("momentum", "long")
        text = m.prometheus_text()
        assert "trading_events_total" in text
        assert 'type="market_tick"' in text
        assert "trading_uptime_seconds" in text
        assert "trading_avg_latency_ms" in text

    def test_start_sets_uptime(self):
        import time
        m = MetricsCollector()
        m.start()
        time.sleep(0.01)
        snap = m.snapshot()
        assert snap["uptime_seconds"] > 0
