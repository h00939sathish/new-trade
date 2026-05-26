from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.risk.kill_switch import KillSwitch
from src.risk.reconciliation import reconcile_positions
from src.schemas.events import EventType, OrderSide, OrderType, ProductType
from src.utils.retry import with_retry


@pytest.mark.asyncio
async def test_kill_switch_mechanism():
    ks = KillSwitch()
    ks.reset()
    assert not ks.active

    # Create mocks
    mock_system = MagicMock()
    mock_execution = MagicMock()
    mock_portfolio = MagicMock()
    mock_strategy = MagicMock()

    mock_execution._open_orders = {"ORD1": MagicMock()}
    mock_execution.cancel_order = AsyncMock()
    mock_execution.place_order = AsyncMock()
    mock_portfolio._positions = {"RELIANCE": {"quantity": 10}}
    mock_strategy._running = True

    mock_system.execution = mock_execution
    mock_system.portfolio_opt = mock_portfolio
    mock_system.strategy_gen = mock_strategy
    mock_system.market_intel = AsyncMock()

    # Set limits: daily loss limit 5000, drawdown 5%
    ks.setup(max_daily_loss=5000.0, max_drawdown_pct=0.05, initial_capital=100000.0)

    # 1. Test safe limits
    triggered = await ks.check_limits(
        current_capital=100000.0,
        current_pnl=-1000.0,
        peak_capital=100000.0,
        system=mock_system
    )
    assert not triggered
    assert not ks.active

    # 2. Test daily loss limit breach (-6000 PnL)
    triggered = await ks.check_limits(
        current_capital=94000.0,
        current_pnl=-6000.0,
        peak_capital=100000.0,
        system=mock_system
    )
    assert triggered
    assert ks.active
    assert "Daily loss limit breached" in ks.reason

    # Verify action side-effects on system:
    # Strategy generator loop should be stopped
    assert not mock_strategy._running
    # open orders cancelled
    mock_execution.cancel_order.assert_called_with("ORD1")
    # open positions market closed
    mock_execution.place_order.assert_called_with(
        instrument="RELIANCE",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10,
        product=ProductType.MIS
    )

@pytest.mark.asyncio
async def test_position_reconciliation():
    mock_system = MagicMock()
    mock_broker = AsyncMock()
    mock_execution = MagicMock()
    mock_portfolio = MagicMock()

    mock_execution._broker = mock_broker
    mock_portfolio._positions = {
        "RELIANCE": {"quantity": 5, "avg_cost": 100.0},
        "TCS": {"quantity": 0, "avg_cost": 0.0}
    }
    mock_portfolio.emit = AsyncMock()
    mock_portfolio._emit_portfolio_update = AsyncMock()
    mock_portfolio.get_total_exposure = MagicMock(return_value=500.0)
    mock_portfolio._capital = 100000.0
    mock_portfolio._pnl = 0.0
    mock_portfolio._peak_capital = 100500.0

    mock_system.execution = mock_execution
    mock_system.portfolio_opt = mock_portfolio

    # Broker returns RELIANCE has 10 (mismatch)
    mock_broker.get_positions.return_value = [
        {"tradingsymbol": "RELIANCE", "quantity": 10}
    ]

    await reconcile_positions(mock_system)

    # Local position should be updated to 10
    assert mock_portfolio._positions["RELIANCE"]["quantity"] == 10
    # Emit should have been called with a RISK_BREACH event
    mock_portfolio.emit.assert_called()
    called_event = mock_portfolio.emit.call_args[0][0]
    assert called_event.event_type == EventType.RISK_BREACH
    assert called_event.data["passed"] is False
    assert called_event.data["check_name"] == "position_reconciliation"

@pytest.mark.asyncio
async def test_retry_helper():
    call_count = 0

    async def transient_fail():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("Timeout")
        return "Success"

    # Should succeed on the 3rd attempt
    res = await with_retry(transient_fail, max_retries=3, base_delay=0.01)
    assert res == "Success"
    assert call_count == 3

    # Should fail after max retries
    call_count_2 = 0
    async def always_fail():
        nonlocal call_count_2
        call_count_2 += 1
        raise ConnectionError("No internet")

    with pytest.raises(ConnectionError):
        await with_retry(always_fail, max_retries=2, base_delay=0.01)
    assert call_count_2 == 2
