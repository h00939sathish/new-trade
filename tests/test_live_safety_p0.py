import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, UTC
from src.connectors.angel.client import AngelClient
from src.agents.execution import ExecutionAgent
from src.schemas.events import OrderEvent, Exchange, OrderSide, OrderType, ProductType
from src.risk.position_registry import position_registry

@pytest.mark.asyncio
async def test_angel_token_refresh_resilience():
    """Verify that token refresh handles HTTP errors correctly and triggers re-login on failure."""
    client = AngelClient()
    client._password = "test_password"
    client._totp = "123456"
    client._feed_token = "old_feed"
    client._jwt_token = "old_jwt"
    client._refresh_token = "old_refresh"
    
    # Mock smart_api methods
    client.smart_api.generateToken = AsyncMock(return_value={"status": False, "message": "Invalid Token"})
    
    # We expect _refresh_login to catch the error and call _login
    with patch.object(client, "_login", new_callable=AsyncMock) as mock_login:
        await client._refresh_login()
        # _login should be called because generateToken returned False status
        mock_login.assert_called_once()

@pytest.mark.asyncio
async def test_execution_ghost_position_tag_fallback(tmp_path):
    """Verify that the live order polling loop falls back to checking the tag field if broker_order_id is missing."""
    db_path = tmp_path / "order_state_ghost.db"
    broker_mock = AsyncMock()
    # Mock the broker returning an order that has no broker_order_id match but has a matching tag
    broker_mock.get_orders.return_value = [
        {
            "order_id": "real_broker_123",
            "tag": "local_event_uuid_123",
            "status": "COMPLETE",
            "filled_quantity": 10,
            "average_price": 100.0,
            "variety": "NORMAL"
        }
    ]
    
    from src.event_store.memory import InMemoryEventStore
    agent = ExecutionAgent(broker=broker_mock, order_db_path=db_path, event_store=InMemoryEventStore())
    await agent.start()
    
    # Simulate an order that failed to save its broker_order_id due to a timeout
    order = OrderEvent.create(
        instrument="RELIANCE",
        exchange=Exchange.NSE,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        price=100.0,
        product=ProductType.MIS,
        data={"status": "rejected"}  # marked rejected locally
    )
    # The event_id acts as the tag sent to the broker
    order.event_id = "local_event_uuid_123"
    
    agent._open_orders[order.event_id] = order
    
    # Run the reconciliation manually (or the loop)
    await agent.reconcile_orders()
    
    # The order should have been popped from _open_orders and marked FILLED
    assert order.event_id not in agent._open_orders
    
@pytest.mark.asyncio
async def test_execution_shutdown_reads_ssot(tmp_path):
    """Ensure on_stop reads open positions from the PositionRegistry SSOT instead of local portfolio_agent cache."""
    db_path = tmp_path / "order_state_shutdown.db"
    broker_mock = AsyncMock()
    broker_mock.place_order.return_value = "kite_close_123"
    
    from src.event_store.memory import InMemoryEventStore
    agent = ExecutionAgent(broker=broker_mock, order_db_path=db_path, event_store=InMemoryEventStore())
    
    # Fake system and portfolio agent
    class DummySystem:
        pass
    class DummyPortfolio:
        pass
    
    agent.system = DummySystem()
    agent.system.portfolio_opt = DummyPortfolio()
    
    await agent.start()
    
    # Set up SSOT with an open position
    position_registry.clear()
    position_registry.update_position("RELIANCE", 10, 2500.0, ProductType.MIS)
    
    # Note: portfolio_agent._positions might NOT have the current quantity if it only tracks totals.
    # The shutdown logic should query PositionRegistry.get_all_positions().
    
    # For testing, we mock the place_order to see if it's called with the correct close params
    with patch.object(agent, "place_order", new_callable=AsyncMock) as mock_place:
        await agent.on_stop()
        
        # It should call place_order to SELL 10 RELIANCE
        mock_place.assert_called_once_with(
            instrument="RELIANCE",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=10,
            product=ProductType.MIS
        )
