"""
Regression tests for FIX P1.1 — SL trigger_price propagation.

Before P1.1, the order code at src/agents/execution.py:605-622 upgraded
MIS orders to Cover Orders only if trigger_price was provided, and
nothing upstream was providing it. The result was that SL on long
positions was log-only ("SOFTWARE STOP LOSS ALERT — Assuming Native
Broker CO handles this") but no actual broker-level SL existed.

These tests verify the trigger_price plumbing:
1. signal with stop_loss_pct → trigger_price is computed and passed to
   OrderEvent.create
2. signal without stop_loss_pct → trigger_price is None
3. signal with price=0 → trigger_price is None (defensive)
4. SHORT signal → trigger_price is above entry price
5. After risk approval, the OrderEvent in _pending_orders has the
   correct trigger_price
"""

import pytest

from src.agents.execution import ExecutionAgent
from src.risk.kill_switch import KillSwitch
from src.schemas.events import (
    EventType,
    OrderSide,
)


@pytest.fixture(autouse=True)
def reset_kill_switch():
    """KillSwitch is also a singleton. Don't let prior tests leave it on."""
    KillSwitch().reset()
    yield
    KillSwitch().reset()


async def _make_agent():
    # No event_store — tests don't need a real bus
    agent = ExecutionAgent()
    return agent


@pytest.mark.asyncio
async def test_long_signal_with_sl_pct_sets_trigger_below_entry():
    """BUY signal with sl_pct=0.02 and price=1300 → trigger_price=1274."""
    agent = await _make_agent()

    signal = {
        "instrument": "RELIANCE",
        "direction": "long",
        "confidence": 0.5,
        "price": 1300.0,
        "strategy": "momentum",
        "stop_loss_pct": 0.02,
        "product": "mis",
    }

    await agent._execute_approved_signal(signal, correlation_id="test-long")

    # The order should be in _pending_orders after PROPOSED is emitted
    assert len(agent._pending_orders) == 1, (
        f"Expected 1 pending order, got {len(agent._pending_orders)}"
    )
    order = next(iter(agent._pending_orders.values()))
    assert order.trigger_price == pytest.approx(1274.0, abs=0.01), (
        f"Expected trigger_price=1274.0 (1300 * 0.98), got {order.trigger_price}"
    )
    assert order.product.value == "mis"
    assert order.side == OrderSide.BUY


@pytest.mark.asyncio
async def test_short_signal_with_sl_pct_sets_trigger_above_entry():
    """SELL signal with sl_pct=0.02 and price=1310 → trigger_price=1336.2."""
    agent = await _make_agent()

    signal = {
        "instrument": "RELIANCE",
        "direction": "short",
        "confidence": 0.5,
        "price": 1310.0,
        "strategy": "momentum",
        "stop_loss_pct": 0.02,
        "product": "mis",
    }

    await agent._execute_approved_signal(signal, correlation_id="test-short")

    assert len(agent._pending_orders) == 1
    order = next(iter(agent._pending_orders.values()))
    assert order.trigger_price == pytest.approx(1336.2, abs=0.01), (
        f"Expected trigger_price=1336.2 (1310 * 1.02), got {order.trigger_price}"
    )
    assert order.side == OrderSide.SELL


@pytest.mark.asyncio
async def test_signal_without_sl_pct_has_no_trigger():
    """Defensive case: signal without stop_loss_pct → trigger_price=None."""
    agent = await _make_agent()

    signal = {
        "instrument": "RELIANCE",
        "direction": "long",
        "confidence": 0.5,
        "price": 1300.0,
        "strategy": "momentum",
        "product": "mis",
    }
    # explicitly no stop_loss_pct
    assert "stop_loss_pct" not in signal

    await agent._execute_approved_signal(signal, correlation_id="test-no-sl")

    assert len(agent._pending_orders) == 1
    order = next(iter(agent._pending_orders.values()))
    assert order.trigger_price is None, f"Expected trigger_price=None, got {order.trigger_price}"


@pytest.mark.asyncio
async def test_signal_with_zero_price_does_not_create_order():
    """Defensive case: price=0 → no order should be created.

    With price=0, _calculate_quantity returns 0 and the agent returns
    early before any order is built. This is the correct defensive
    behavior; the test verifies we don't crash and don't put a malformed
    order into _pending_orders.
    """
    agent = await _make_agent()

    signal = {
        "instrument": "RELIANCE",
        "direction": "long",
        "confidence": 0.5,
        "price": 0.0,
        "strategy": "momentum",
        "stop_loss_pct": 0.02,
        "product": "mis",
    }

    # Should not raise
    await agent._execute_approved_signal(signal, correlation_id="test-zero")

    # No order created
    assert len(agent._pending_orders) == 0, (
        f"Expected 0 pending orders for price=0, got {len(agent._pending_orders)}"
    )


@pytest.mark.asyncio
async def test_signal_with_sl_pct_zero_has_no_trigger():
    """Defensive case: sl_pct=0 (no SL requested) → trigger_price=None."""
    agent = await _make_agent()

    signal = {
        "instrument": "RELIANCE",
        "direction": "long",
        "confidence": 0.5,
        "price": 1300.0,
        "strategy": "momentum",
        "stop_loss_pct": 0.0,  # explicitly no SL
        "product": "mis",
    }

    await agent._execute_approved_signal(signal, correlation_id="test-sl-zero")

    assert len(agent._pending_orders) == 1
    order = next(iter(agent._pending_orders.values()))
    assert order.trigger_price is None, (
        f"Expected trigger_price=None for sl_pct=0, got {order.trigger_price}"
    )


@pytest.mark.asyncio
async def test_order_proposed_event_has_trigger_price():
    """The OrderEvent that gets emitted to the bus should carry trigger_price.

    This is what the broker (or paper simulator) reads to decide whether
    to upgrade the order to a Cover Order.
    """
    agent = await _make_agent()

    # Capture emitted events
    emitted = []
    original_emit = agent.emit

    async def capture_emit(event):
        emitted.append(event)
        await original_emit(event)

    agent.emit = capture_emit

    signal = {
        "instrument": "RELIANCE",
        "direction": "long",
        "confidence": 0.5,
        "price": 1300.0,
        "strategy": "momentum",
        "stop_loss_pct": 0.02,
        "product": "mis",
    }

    await agent._execute_approved_signal(signal, correlation_id="test-emit")

    # Find the ORDER_PROPOSED event
    proposed = [e for e in emitted if e.event_type == EventType.ORDER_PROPOSED]
    assert len(proposed) == 1, f"Expected 1 ORDER_PROPOSED, got {len(proposed)}"
    assert proposed[0].trigger_price == pytest.approx(1274.0, abs=0.01), (
        f"Expected trigger_price=1274.0 in emitted event, got {proposed[0].trigger_price}"
    )
    # The 'data' dict should also reflect it (for downstream consumers reading data)
    assert proposed[0].data.get("trigger_price") == pytest.approx(1274.0, abs=0.01)
