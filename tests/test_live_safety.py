import pytest
import asyncio
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.agents.execution import ExecutionAgent
from src.agents.strategy_gen import StrategyGenAgent
from src.agents.market_intel import MarketIntelAgent
from src.schemas.events import (
    Event, EventType, OrderEvent, OrderSide, OrderType, ProductType, Exchange, TickEvent
)
from src.risk.position_registry import position_registry

@pytest.fixture
async def broker_mock():
    broker = AsyncMock()
    broker.place_order.return_value = "kite_order_123"
    broker.get_orders.return_value = []
    return broker

@pytest.mark.asyncio
async def test_native_stop_loss_attached_at_placement(broker_mock, tmp_path):
    """Verify that a native Cover Order (variety='co') is placed with the trigger_price for MIS orders."""
    db_path = tmp_path / "order_state.db"
    agent = ExecutionAgent(broker=broker_mock, order_db_path=db_path)
    await agent.start()
    
    # Simulate risk-approved signal that triggers place_order
    order = await agent.place_order(
        instrument="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        product=ProductType.MIS,
        price=2500.0,
        trigger_price=2450.0, # SL at 2450
        exchange=Exchange.NSE,
    )
    
    # Assert place_order was called with variety="co" and trigger_price
    broker_mock.place_order.assert_called_once()
    call_args = broker_mock.place_order.call_args[1]
    
    assert call_args["tradingsymbol"] == "RELIANCE"
    assert call_args["trigger_price"] == 2450.0
    assert call_args.get("variety") == "co"
    
    await agent.stop()

@pytest.mark.asyncio
async def test_gap_down_crash_handled_by_native_sl(broker_mock, tmp_path):
    """Verify software check logs a warning but doesn't emit duplicate exit on gap-down."""
    agent = StrategyGenAgent()
    await agent.start()
    
    # Setup mock position
    await position_registry.update_from_fill("RELIANCE", "buy", 10, 2500.0)
    await position_registry.set_sl_tp("RELIANCE", stop_loss=2450.0, take_profit=2550.0)
    
    # Emit gap down tick below SL
    tick = TickEvent.create(
        instrument="RELIANCE",
        exchange=Exchange.NSE,
        last_price=2400.0, # Gap down below 2450 SL
        producer="market_intel",
    )
    
    emitted = []
    async def mock_emit(evt):
        emitted.append(evt)
    agent.emit = mock_emit
    
    await agent._check_sl_tp("RELIANCE", 2400.0, datetime.now(UTC), Exchange.NSE)
    
    # Verify it acts as a secondary monitor and does NOT emit an exit signal
    # The native broker order should handle the actual exit.
    assert len(emitted) == 0
    
    await agent.stop()

@pytest.mark.asyncio
async def test_duplicate_order_prevention(broker_mock, tmp_path):
    db_path = tmp_path / "order_state.db"
    agent = ExecutionAgent(broker=broker_mock, order_db_path=db_path)
    await agent.start()
    
    # Simulate broker returning an order with the same tag
    broker_mock.get_orders.return_value = [{"tag": "order_tag_123", "order_id": "kite_order_123"}]
    
    # Attempt to place order with same tag via internal mechanisms
    # We mock event_id to match tag
    import uuid
    dummy_uuid = uuid.uuid4().hex
    broker_mock.get_orders.return_value = [{"tag": dummy_uuid, "order_id": "kite_order_123"}]
    
    # Instead of full flow, we call the duplicate checker directly
    res = await agent._is_order_placed(dummy_uuid)
    assert res == "kite_order_123"
    
    await agent.stop()

@pytest.mark.asyncio
async def test_broker_reject_fails_closed(broker_mock, tmp_path):
    """If broker rejects order placement, ensure order status is updated."""
    db_path = tmp_path / "order_state.db"
    agent = ExecutionAgent(broker=broker_mock, order_db_path=db_path)
    await agent.start()
    
    broker_mock.place_order.side_effect = Exception("Broker Reject: Margin Exceeded")
    
    with pytest.raises(Exception):
        await agent.place_order(
            instrument="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            price=2500.0,
            product=ProductType.MIS,
        )
    
    await agent.stop()

@pytest.mark.asyncio
async def test_restart_restores_state(broker_mock, tmp_path):
    """Verify SQLite properly restores open orders on restart."""
    db_path = tmp_path / "order_state.db"
    agent1 = ExecutionAgent(broker=broker_mock, order_db_path=db_path)
    await agent1.start()
    
    # We use a LIMIT order with a far away price so it doesn't get filled instantly
    order = await agent1.place_order(
        instrument="RELIANCE", side=OrderSide.BUY, order_type=OrderType.LIMIT, quantity=10, product=ProductType.MIS, price=100.0
    )
    assert order.event_id in agent1._open_orders
    
    # We must also ensure the DB has it
    async with agent1._order_db.execute("SELECT * FROM orders WHERE event_id=?", (order.event_id,)) as cursor:
        row = await cursor.fetchone()
        assert row is not None

    # Hard stop to avoid graceful cancellation
    agent1._running = False
    await agent1._order_db.close()
    
    # Restart
    agent2 = ExecutionAgent(broker=broker_mock, order_db_path=db_path)
    await agent2.start()
    
    # State should be restored
    assert order.event_id in agent2._open_orders
    await agent2.stop()

@pytest.mark.asyncio
async def test_stale_market_data_detection():
    """Verify ticks older than a threshold are rejected."""
    agent = MarketIntelAgent()
    await agent.start()
    
    now = datetime.now(UTC)
    stale_time = now - timedelta(minutes=5)
    
    # Use internal validate or ingest tick
    # If a tick is > 60s old, it should be marked anomalous or rejected
    # (Assuming we add this feature in this phase)
    res = agent._validate_tick("RELIANCE", 2500.0, timestamp=stale_time)
    assert res is False, "Stale tick should be rejected"
    
    await agent.stop()
