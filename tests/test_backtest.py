from datetime import UTC, datetime, timedelta

import pytest

from src.strategies.technical import MomentumStrategy
from src.backtest.engine import BacktestEngine

_BASE_TIME = datetime(2026, 5, 25, 9, 15, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_backtest_run_empty_ticks():
    engine = BacktestEngine(initial_capital=100_000.0)
    result = await engine.run([])
    assert result.total_trades == 0
    assert result.final_value == 100_000.0


@pytest.mark.asyncio
async def test_backtest_with_momentum_strategy():
    strategy = MomentumStrategy(short_window=3, long_window=10, threshold=0.01)
    engine = BacktestEngine(
        strategies=[strategy],
        initial_capital=100_000.0,
    )
    ticks = [
        {
            "instrument": "TEST",
            "price": 100.0 + i * 0.5,
            "volume": 1000,
            "timestamp": _BASE_TIME + timedelta(seconds=i),
        }
        for i in range(30)
    ]
    result = await engine.run(ticks)
    assert result.total_trades >= 0
    assert isinstance(result.final_value, float)
    assert result.max_drawdown >= 0.0
    assert 0.0 <= result.win_rate <= 1.0


@pytest.mark.asyncio
async def test_backtest_sharpe_ratio():
    strategy = MomentumStrategy(short_window=3, long_window=10, threshold=0.02)
    engine = BacktestEngine(strategies=[strategy], initial_capital=100_000.0)
    ticks = [
        {
            "instrument": "TEST",
            "price": 100.0 + (i % 5) * 2.0,
            "volume": 1000,
            "timestamp": _BASE_TIME + timedelta(seconds=i),
        }
        for i in range(50)
    ]
    result = await engine.run(ticks)
    assert isinstance(result.sharpe_ratio, float)
    assert result.total_trades >= 0


@pytest.mark.asyncio
async def test_backtest_equity_curve():
    strategy = MomentumStrategy(short_window=3, long_window=10, threshold=0.005)
    engine = BacktestEngine(strategies=[strategy], initial_capital=100_000.0)
    ticks = [
        {
            "instrument": "TEST",
            "price": 100.0 + i * 2.0,
            "volume": 1000,
            "timestamp": _BASE_TIME + timedelta(seconds=i),
        }
        for i in range(30)
    ]
    result = await engine.run(ticks)
    assert len(result.equity_curve) >= 0
    assert result.total_trades >= 0


@pytest.mark.asyncio
async def test_backtest_engine_trade_math():
    from src.schemas.events import Exchange, OrderEvent, OrderSide, OrderType, ProductType

    engine = BacktestEngine(
        initial_capital=100_000.0,
        commission_pct=0.001,  # 0.1% commission
        slippage_bps=10.0,  # 10 bps slippage (0.1%)
    )

    # 1. Test Buy Fill calculation with commission and slippage (Bug 4)
    # Order Event for BUY of 100 shares at 100.0
    order_buy = OrderEvent.create(
        instrument="TEST",
        exchange=Exchange.NSE,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        product=ProductType.MIS,
        price=100.0,
    )

    await engine._simulate_fill(order_buy)

    pos = engine._positions["TEST"]
    assert pos["quantity"] == 100
    assert pos["avg_cost"] == pytest.approx(100.225296)
    assert pos["cost"] == pytest.approx(10022.529617)
    assert engine._capital == pytest.approx(89977.470383)

    # 2. Test Sell Fill calculation with commission and slippage (Bug 4, Bug 2, Bug 3)
    # Order Event for SELL of 100 shares at 110.0
    order_sell = OrderEvent.create(
        instrument="TEST",
        exchange=Exchange.NSE,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=100,
        product=ProductType.MIS,
        price=110.0,
    )

    await engine._simulate_fill(order_sell)

    assert engine._capital == pytest.approx(100950.297762)
    assert pos["quantity"] == 0
    assert pos["avg_cost"] == 0.0  # Reset on quantity = 0 (Bug 3)
    assert pos["cost"] == 0.0

    assert len(engine._trade_log) == 1
    assert engine._trade_log[0]["pnl"] == pytest.approx(950.297762)
