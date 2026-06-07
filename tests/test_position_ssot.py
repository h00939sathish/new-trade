"""
Regression tests for FIX P1.2 — PositionRegistry is the single source of truth.

Before P1.2, PortfolioOptimizationAgent kept its own _positions dict
with quantity and avg_cost in addition to PositionRegistry tracking the
same fields. The two were kept in sync only because _on_fill called
both. This test verifies that get_position() and get_total_exposure()
read from the registry, so they cannot diverge.

Also verifies that fills flowing through the portfolio agent result in
the same quantity/avg_cost view as direct registry queries.
"""

import pytest

from src.agents.portfolio import PortfolioOptimizationAgent
from src.event_store.memory import InMemoryEventStore
from src.risk.position_registry import position_registry
from src.schemas.events import (
    Event,
    EventMetadata,
    EventType,
)


@pytest.fixture(autouse=True)
def reset_state():
    position_registry.reset()
    yield
    position_registry.reset()


def _fill_event(instrument, side, qty, price, product="mis"):
    return Event(
        event_type=EventType.FILL,
        stream=f"fill.{instrument}",
        data={
            "instrument": instrument,
            "side": side,
            "fill_quantity": qty,
            "fill_price": price,
            "product": product,
            "commission": 0.0,
        },
        metadata=EventMetadata(producer="execution"),
    )


@pytest.mark.asyncio
async def test_get_position_reads_from_registry():
    """get_position() should return the same quantity/avg_cost as the registry."""
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
    await p.event_store.connect()

    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))

    # Direct registry read
    reg = position_registry.get_position("RELIANCE")
    # Agent read
    pos = p.get_position("RELIANCE")

    assert pos["quantity"] == reg["quantity"] == 10
    assert pos["avg_cost"] == reg["avg_price"] == 2500.0
    assert pos["side"] == "long"


@pytest.mark.asyncio
async def test_get_total_exposure_reads_from_registry():
    """get_total_exposure() should equal sum of |qty * avg_price| from registry."""
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
    await p.event_store.connect()

    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))
    await p._on_fill(_fill_event("TCS", "buy", 5, 3500.0))

    reg_total = sum(
        abs(pos.get("quantity", 0)) * pos.get("avg_price", 0.0)
        for pos in position_registry.get_all_positions().values()
    )
    assert p.get_total_exposure() == reg_total == 10 * 2500.0 + 5 * 3500.0


@pytest.mark.asyncio
async def test_portfolio_cannot_diverge_from_registry():
    """If the registry is updated externally (e.g., reconciliation), the
    portfolio agent's view should reflect the new state on the next read.

    Before P1.2, the portfolio agent had its own _positions[instrument]
    dict that wouldn't see this external update. After P1.2, get_position()
    always reads from the registry.
    """
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
    await p.event_store.connect()

    # Initial fill
    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))
    assert p.get_position("RELIANCE")["quantity"] == 10

    # External reconciliation injects a position directly into the registry
    await position_registry.sync_from_portfolio(
        {
            "RELIANCE": {"quantity": 25, "avg_cost": 2480.0},  # different from 10
        }
    )

    # The portfolio agent should now reflect 25 (from registry), not 10
    pos = p.get_position("RELIANCE")
    assert pos["quantity"] == 25, (
        f"Portfolio should read from registry, got quantity={pos['quantity']} "
        f"but registry has 25. The portfolio agent's _positions dict is "
        f"diverging from the SSOT."
    )
    assert pos["avg_cost"] == 2480.0


@pytest.mark.asyncio
async def test_realized_pnl_uses_registry_avg_price():
    """Sell fills should use the registry's avg_price as the cost basis
    (not the portfolio agent's own dict, which doesn't track this)."""
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
    await p.event_store.connect()

    # Buy 10 @ 2500, then buy 10 @ 2600 (avg = 2550)
    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))
    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2600.0))

    # Sell 5 @ 2700 (PnL = (2700 - 2550) * 5 = 750)
    await p._on_fill(_fill_event("RELIANCE", "sell", 5, 2700.0))

    # Realized PnL should be 750
    expected_pnl = (2700.0 - 2550.0) * 5  # 750
    assert p._pnl == pytest.approx(expected_pnl, abs=0.01), (
        f"Expected PnL={expected_pnl}, got {p._pnl}"
    )


@pytest.mark.asyncio
async def test_health_open_positions_count_matches_registry():
    """health()['open_positions'] should count from the registry."""
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=500_000.0, event_store=store)
    await p.event_store.connect()

    # Empty
    h0 = await p.health()
    assert h0["open_positions"] == 0

    # One open position
    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))
    h1 = await p.health()
    assert h1["open_positions"] == 1
    assert h1["open_positions"] == len(position_registry.get_all_positions())


@pytest.mark.asyncio
async def test_health_total_exposure_matches_registry():
    """health()['total_exposure'] should be computed from the registry."""
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=500_000.0, event_store=store)
    await p.event_store.connect()

    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))
    await p._on_fill(_fill_event("TCS", "buy", 5, 3500.0))

    h = await p.health()
    expected = 10 * 2500.0 + 5 * 3500.0
    assert h["total_exposure"] == expected


@pytest.mark.asyncio
async def test_portfolio_event_payload_includes_registry_data():
    """The PORTFOLIO_UPDATE event payload should include quantity/avg_cost
    from the registry for every instrument the portfolio is tracking."""
    store = InMemoryEventStore()
    await store.connect()
    p = PortfolioOptimizationAgent(initial_capital=500_000.0, event_store=store)
    await p.event_store.connect()

    await p._on_fill(_fill_event("RELIANCE", "buy", 10, 2500.0))
    payloads = p._build_position_payloads()
    reliance = next((x for x in payloads if x["instrument"] == "RELIANCE"), None)
    assert reliance is not None
    assert reliance["quantity"] == 10
    assert reliance["avg_cost"] == 2500.0
    # cumulative accounting should also be in the payload
    assert reliance["total_bought"] == 10
    assert reliance["total_sold"] == 0
