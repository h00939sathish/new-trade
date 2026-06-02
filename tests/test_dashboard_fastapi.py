from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from dashboard.server import create_app
from src.risk.kill_switch import KillSwitch

AUTH_TOKEN = "operator-test-token"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AUTH_TOKEN}"}


@pytest.fixture(autouse=True)
def reset_dashboard_auth_state(monkeypatch):
    monkeypatch.delenv("TRA_HTTP_AUTH_TOKEN", raising=False)
    KillSwitch().reset()
    yield
    KillSwitch().reset()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestFastAPIDashboard:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["status"] == "ok"
        assert data["broker_health"]["available"] is False
        assert data["reconciliation"]["matched"] is None
        assert data["telemetry"]["live_trading_configured"] is False

    def test_api_health_alias(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["status"] == "ok"
        assert data["broker_health"]["available"] is False

    def test_index_redirect(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert "dashboard" in data
        assert data["dashboard"] == "/control/"

    def test_metrics_aliases(self, client):
        for path in ("/metrics", "/api/metrics"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert "trading_uptime_seconds" in resp.text

    def test_paper_report(self, client):
        resp = client.get("/api/paper-report")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert "summary" in data
        assert "orders" in data
        assert "positions" in data

    def test_live_report(self, client):
        resp = client.get("/api/live-report")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["telemetry"]["live_trading_configured"] is False
        assert data["reconciliation"]["matched"] is None
        assert data["warnings"]
        assert data["summary"]["total_trades"] == 0
        assert data["summary"]["win_rate_pct"] == 0.0

    def test_validation_report(self, client):
        resp = client.get("/api/output/validation_report")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["available"] is False
        assert "summary" in data
        assert "trading_efficiency" in data
        assert data["summary"]["sharpe_ratio"] is None

    def test_analysis_results(self, client):
        resp = client.get("/api/output/analysis_results")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["market_data_symbols"] == []
        assert data["sentiment"] == {}

    def test_experiment_report(self, client):
        resp = client.get("/api/output/experiment_report")
        assert resp.status_code == 200

    def test_pending_orders(self, client):
        resp = client.get("/api/orders/pending")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["orders"] == []

    def test_reports_reflect_execution_state(self):
        now = datetime.now(timezone.utc)
        open_order = SimpleNamespace(
            data={
                "instrument": "RELIANCE",
                "side": "sell",
                "quantity": 38,
                "status": "pending",
            },
            timestamp=now,
        )
        fill = SimpleNamespace(
            order_id="fill-1",
            instrument="INFY",
            side=SimpleNamespace(value="sell"),
            fill_quantity=39,
            fill_price=1270.46,
            event_id="broker-fill-1",
            timestamp=now,
        )
        execution = SimpleNamespace(
            _open_orders={"order-1": open_order},
            _filled_orders={"INFY": [fill]},
            _twap_orders={},
            _broker=None,
            _paper_trading=True,
        )

        class _System:
            async def health(self):
                return {}

        system = _System()
        system.execution = execution
        system.portfolio_opt = None

        with TestClient(create_app(system=system)) as client:
            pending_resp = client.get("/api/orders/pending")
            pending_data = json.loads(pending_resp.text)
            assert pending_data["total"] == 1
            assert pending_data["orders"][0]["symbol"] == "RELIANCE"

            report_resp = client.get("/api/paper-report")
            report_data = json.loads(report_resp.text)
            assert report_data["summary"]["total_trades"] == 1
            assert report_data["recent_trades"][0]["symbol"] == "INFY"

    def test_strategies(self, client):
        resp = client.get("/api/control-plane/strategies")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert "strategies" in data

    def test_overview(self, client):
        resp = client.get("/api/control-plane/overview")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert "broker" in data
        assert "controls" in data
        assert "health" in data
        assert data["health"]["broker_health"]["available"] is False
        assert data["health"]["reconciliation"]["matched"] is None

    def test_overview_alias(self, client):
        resp = client.get("/api/overview")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert "broker" in data
        assert data["health"]["status"] == "ok"

    def test_control_endpoint_rejects_unauthenticated_request(self, monkeypatch):
        monkeypatch.setenv("TRA_HTTP_AUTH_TOKEN", AUTH_TOKEN)
        with TestClient(create_app()) as client:
            resp = client.post("/api/control-plane/controls/emergency-stop")
        assert resp.status_code == 401
        assert KillSwitch().active is False

    def test_control_endpoint_rejects_when_auth_not_configured(self):
        with TestClient(create_app()) as client:
            resp = client.post("/api/control-plane/controls/emergency-stop", headers=_auth_headers())
        assert resp.status_code == 503

    def test_bearer_token_accepts_control_request(self, monkeypatch):
        monkeypatch.setenv("TRA_HTTP_AUTH_TOKEN", AUTH_TOKEN)
        with TestClient(create_app()) as client:
            resp = client.post("/api/control-plane/controls/approvals", headers=_auth_headers())
        assert resp.status_code == 200

    def test_reset_requires_active_kill_switch(self, monkeypatch):
        monkeypatch.setenv("TRA_HTTP_AUTH_TOKEN", AUTH_TOKEN)
        with TestClient(create_app()) as client:
            resp = client.post("/api/control-plane/controls/reset", headers=_auth_headers())
        assert resp.status_code == 409
        assert KillSwitch().active is False

    def test_reset_clears_active_kill_switch(self, monkeypatch):
        monkeypatch.setenv("TRA_HTTP_AUTH_TOKEN", AUTH_TOKEN)
        kill_switch = KillSwitch()
        kill_switch._active = True
        kill_switch._reason = "test halt"

        with TestClient(create_app()) as client:
            resp = client.post("/api/control-plane/controls/reset", headers=_auth_headers())
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["active"] is False
        assert kill_switch.active is False

    def test_emergency_stop_triggers_kill_switch(self, monkeypatch):
        monkeypatch.setenv("TRA_HTTP_AUTH_TOKEN", AUTH_TOKEN)
        system = SimpleNamespace(
            strategy_gen=SimpleNamespace(_running=True),
            market_intel=SimpleNamespace(emit=AsyncMock()),
            execution=SimpleNamespace(_open_orders={}, cancel_order=AsyncMock(), place_order=AsyncMock()),
            portfolio_opt=SimpleNamespace(_positions={}),
        )

        with TestClient(create_app(system=system)) as client:
            resp = client.post(
                "/api/control-plane/controls/emergency-stop",
                json={"reason": "operator test halt"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["active"] is True
        assert data["reason"] == "operator test halt"
        assert KillSwitch().active is True
        assert KillSwitch().reason == "operator test halt"
        assert system.strategy_gen._running is False
        system.market_intel.emit.assert_awaited_once()

    def test_trade_execute(self, monkeypatch):
        monkeypatch.setenv("TRA_HTTP_AUTH_TOKEN", AUTH_TOKEN)
        with TestClient(create_app()) as client:
            resp = client.post(
                "/api/trade/execute",
                json={"symbol": "RELIANCE", "side": "BUY"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["status"] == "ok"
