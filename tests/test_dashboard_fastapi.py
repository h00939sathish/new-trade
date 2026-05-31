from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from dashboard.server import create_app


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

    def test_index_redirect(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert "dashboard" in data
        assert data["dashboard"] == "/control/"

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

    def test_experiment_report(self, client):
        resp = client.get("/api/output/experiment_report")
        assert resp.status_code == 200

    def test_pending_orders(self, client):
        resp = client.get("/api/orders/pending")
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["orders"] == []

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

    def test_emergency_stop(self, client):
        resp = client.post("/api/control-plane/controls/emergency-stop")
        assert resp.status_code == 200

    def test_reset(self, client):
        resp = client.post("/api/control-plane/controls/reset")
        assert resp.status_code == 200

    def test_approvals(self, client):
        resp = client.post("/api/control-plane/controls/approvals")
        assert resp.status_code == 200

    def test_trade_execute(self, client):
        resp = client.post(
            "/api/trade/execute",
            json={"symbol": "RELIANCE", "side": "BUY"},
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        data = json.loads(resp.text)
        assert data["status"] == "ok"
