import pytest

from src.agents.reflection_engine import (
    GeminiClient,
    ReflectionEngineAgent,
    generate_synthetic_ticks,
)
from src.backtest.engine import BacktestResult
from src.schemas.events import Exchange, FillEvent, OrderSide


@pytest.fixture
def reflection():
    return ReflectionEngineAgent()


@pytest.mark.asyncio
async def test_reflection_start_stop(reflection: ReflectionEngineAgent):
    await reflection.start()
    assert reflection.status.value == "running"
    health = await reflection.health()
    assert health["agent"] == "reflection_engine"
    assert health["fill_buffer_size"] == 0
    await reflection.stop()
    assert reflection.status.value == "stopped"


@pytest.mark.asyncio
async def test_reflection_subscribes_to_fills(reflection: ReflectionEngineAgent):
    await reflection.start()
    assert any("order.fill" in str(s) for s in reflection._subscribed_event_types)
    await reflection.stop()


@pytest.mark.asyncio
async def test_reflection_accumulates_fills(reflection: ReflectionEngineAgent):
    await reflection.start()
    for i in range(5):
        fill = FillEvent.create(
            order_id=f"ord_{i}",
            instrument="TEST",
            exchange=Exchange.NSE,
            side=OrderSide.BUY,
            fill_price=100.0 + i,
            fill_quantity=10,
        )
        await reflection.on_event(fill)
    assert len(reflection._fill_buffer) == 5
    await reflection.stop()


@pytest.mark.asyncio
async def test_generate_synthetic_ticks():
    ticks = generate_synthetic_ticks(100)
    assert len(ticks) == 100
    for t in ticks:
        assert "instrument" in t
        assert "price" in t
        assert "volume" in t
        assert isinstance(t["price"], float)


@pytest.mark.asyncio
async def test_gemini_fallback():
    client = GeminiClient(api_key="")
    result = BacktestResult()
    result.total_trades = 10
    result.sharpe_ratio = 0.3
    result.total_pnl = 100.0
    result.win_rate = 0.5
    result.max_drawdown = 0.1
    result.profit_factor = 1.2
    hyp = client._fallback_hypothesis(result)
    assert hyp is not None
    assert "strategy" in hyp
    assert "params" in hyp


@pytest.mark.asyncio
async def test_gemini_fallback_no_trades():
    client = GeminiClient(api_key="")
    result = BacktestResult()
    hyp = client._fallback_hypothesis(result)
    assert hyp is None


@pytest.mark.asyncio
async def test_is_improvement():
    baseline = BacktestResult()
    baseline.total_trades = 10
    baseline.sharpe_ratio = 1.0
    baseline.win_rate = 0.5
    baseline.total_pnl = 1000.0
    baseline.max_drawdown = 0.1

    improved = BacktestResult()
    improved.total_trades = 15
    improved.sharpe_ratio = 1.5
    improved.win_rate = 0.6
    improved.total_pnl = 2000.0
    improved.max_drawdown = 0.08

    agent = ReflectionEngineAgent()
    assert agent._is_improvement(baseline, improved) is True


@pytest.mark.asyncio
async def test_is_improvement_not_enough_trades():
    baseline = BacktestResult()
    baseline.total_trades = 1
    baseline.sharpe_ratio = 1.0
    baseline.win_rate = 0.5
    baseline.total_pnl = 100.0
    baseline.max_drawdown = 0.1

    improved = BacktestResult()
    improved.total_trades = 2
    improved.sharpe_ratio = 1.5
    improved.win_rate = 0.6
    improved.total_pnl = 200.0
    improved.max_drawdown = 0.08

    agent = ReflectionEngineAgent()
    assert agent._is_improvement(baseline, improved) is False


@pytest.mark.asyncio
async def test_is_improvement_worse():
    baseline = BacktestResult()
    baseline.total_trades = 10
    baseline.sharpe_ratio = 1.0
    baseline.win_rate = 0.5
    baseline.total_pnl = 1000.0
    baseline.max_drawdown = 0.1

    worse = BacktestResult()
    worse.total_trades = 8
    worse.sharpe_ratio = 0.5
    worse.win_rate = 0.3
    worse.total_pnl = -500.0
    worse.max_drawdown = 0.25

    agent = ReflectionEngineAgent()
    assert agent._is_improvement(baseline, worse) is False


@pytest.mark.asyncio
async def test_result_to_dict():
    r = BacktestResult()
    r.total_trades = 10
    r.total_pnl = 500.0
    r.win_rate = 0.6
    r.sharpe_ratio = 1.2
    r.max_drawdown = 0.05
    r.profit_factor = 2.0

    d = ReflectionEngineAgent._result_to_dict(r)
    assert d["total_trades"] == 10
    assert d["total_pnl"] == 500.0
    assert d["win_rate"] == 0.6
    assert d["sharpe_ratio"] == 1.2
