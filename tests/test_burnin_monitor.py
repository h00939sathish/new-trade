import json
from unittest.mock import MagicMock

import pytest

from src.monitoring.burnin import (
    build_paper_reconciliation_snapshot,
    write_paper_reconciliation_snapshot,
)
from src.risk.position_registry import position_registry


@pytest.fixture(autouse=True)
def reset_positions():
    position_registry.reset()
    yield
    position_registry.reset()


def _system():
    system = MagicMock()
    system.execution._paper_trading = True
    system.execution._open_orders = {}
    system.execution._filled_orders = {"order-1": [MagicMock()]}
    system.portfolio_opt._positions = {
        "RELIANCE": {"quantity": 10, "avg_cost": 100.0},
    }
    return system


def test_snapshot_reports_matching_local_paper_positions():
    position_registry.update_from_fill("RELIANCE", "buy", 10, 100.0)

    snapshot = build_paper_reconciliation_snapshot(_system())

    assert snapshot["status"] == "ok"
    assert snapshot["paper_trading"] is True
    assert snapshot["position_mismatches"] == {}
    assert snapshot["filled_orders"] == 1


def test_snapshot_reports_local_position_mismatch():
    position_registry.update_from_fill("RELIANCE", "buy", 5, 100.0)

    snapshot = build_paper_reconciliation_snapshot(_system())

    assert snapshot["status"] == "mismatch"
    assert snapshot["position_mismatches"] == {
        "RELIANCE": {"portfolio": 10, "registry": 5},
    }


def test_write_snapshot_appends_json_line(tmp_path):
    position_registry.update_from_fill("RELIANCE", "buy", 10, 100.0)
    path = tmp_path / "reconciliation.jsonl"

    snapshot = write_paper_reconciliation_snapshot(_system(), path)

    assert json.loads(path.read_text().strip()) == snapshot
