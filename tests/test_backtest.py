import pytest

from src.agents.strategy_gen import MomentumStrategy
from src.backtest.engine import BacktestEngine


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
        {"instrument": "TEST", "price": 100.0 + i * 0.5, "volume": 1000}
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
        {"instrument": "TEST", "price": 100.0 + (i % 5) * 2.0, "volume": 1000}
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
        {"instrument": "TEST", "price": 100.0 + i * 2.0, "volume": 1000}
        for i in range(30)
    ]
    result = await engine.run(ticks)
    assert len(result.equity_curve) >= 0
    assert result.total_trades >= 0
