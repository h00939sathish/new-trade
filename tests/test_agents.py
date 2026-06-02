import asyncio
import pytest

from src.agents.execution import ExecutionAgent
from src.agents.market_intel import MarketIntelAgent
from src.agents.risk_mgmt import RiskManagementAgent
from src.agents.strategy_gen import MeanReversionStrategy, MomentumStrategy, StrategyGenAgent
from src.event_store.memory import InMemoryEventStore
from src.schemas.events import Exchange


@pytest.fixture
def market_intel():
    return MarketIntelAgent()


@pytest.fixture
def strategy_gen():
    return StrategyGenAgent()


@pytest.fixture
def risk_mgmt():
    return RiskManagementAgent()


@pytest.fixture
def execution():
    return ExecutionAgent()


@pytest.mark.asyncio
async def test_market_intel_start_stop(market_intel: MarketIntelAgent):
    await market_intel.start()
    assert market_intel.status.value == "running"
    health = await market_intel.health()
    assert health["agent"] == "market_intel"
    await market_intel.stop()
    assert market_intel.status.value == "stopped"


@pytest.mark.asyncio
async def test_market_intel_ingest_tick(market_intel: MarketIntelAgent):
    await market_intel.start()
    await market_intel.ingest_tick("RELIANCE", Exchange.NSE, 2500.0, volume=1000, bid=2499, ask=2501)
    latest = market_intel.get_latest_tick("RELIANCE")
    assert latest is not None
    assert latest.data["last_price"] == 2500.0
    await market_intel.stop()


@pytest.mark.asyncio
async def test_market_intel_ingest_ohlcv(market_intel: MarketIntelAgent):
    await market_intel.start()
    await market_intel.ingest_ohlcv("RELIANCE", Exchange.NSE, "minute", 100, 110, 99, 105, 10000)
    latest = market_intel.get_latest_ohlcv("RELIANCE", "minute")
    assert latest is not None
    assert latest.data["close"] == 105
    await market_intel.stop()


@pytest.mark.asyncio
async def test_market_intel_builder():
    agent = MarketIntelAgent()
    agent.add_instrument("RELIANCE")
    agent.add_instrument("TCS")
    agent.set_exchange(Exchange.NSE)
    await agent.start()
    assert agent.status.value == "running"
    await agent.stop()


@pytest.mark.asyncio
async def test_strategy_gen_start_stop(strategy_gen: StrategyGenAgent):
    await strategy_gen.start()
    assert strategy_gen.status.value == "running"
    assert strategy_gen._strategies
    await strategy_gen.stop()
    assert strategy_gen.status.value == "stopped"


@pytest.mark.asyncio
async def test_momentum_strategy():
    strategy = MomentumStrategy(short_window=3, long_window=10, threshold=0.01)
    prices = [100.0] * 9 + [105.0, 106.0, 107.0]
    result = await strategy.evaluate("TEST", prices)
    assert result is not None
    assert result["direction"] == "long"
    assert 0 < result["confidence"] <= 0.95


@pytest.mark.asyncio
async def test_momentum_strategy_insufficient_data():
    strategy = MomentumStrategy(short_window=5, long_window=20, threshold=0.02)
    prices = [100.0] * 10
    result = await strategy.evaluate("TEST", prices)
    assert result is None


@pytest.mark.asyncio
async def test_mean_reversion_strategy():
    strategy = MeanReversionStrategy(window=10, entry_z=1.5, exit_z=0.5)
    prices = [100.0] * 10 + [95.0, 94.0, 93.0]
    result = await strategy.evaluate("TEST", prices)
    assert result is not None
    assert result["direction"] == "long"
    assert "z_score" in result["features"]


@pytest.mark.asyncio
async def test_mean_reversion_strategy_no_signal():
    strategy = MeanReversionStrategy(window=10, entry_z=3.0, exit_z=0.5)
    prices = [100.0] * 13
    result = await strategy.evaluate("TEST", prices)
    assert result is None


@pytest.mark.asyncio
async def test_risk_mgmt_start_stop(risk_mgmt: RiskManagementAgent):
    await risk_mgmt.start()
    assert risk_mgmt.status.value == "running"
    await risk_mgmt.stop()
    assert risk_mgmt.status.value == "stopped"


@pytest.mark.asyncio
async def test_execution_start_stop(execution: ExecutionAgent):
    await execution.start()
    assert execution.status.value == "running"
    await execution.stop()
    assert execution.status.value == "stopped"


@pytest.mark.asyncio
async def test_execution_place_and_cancel(execution: ExecutionAgent):
    await execution.start()
    from src.schemas.events import OrderSide, OrderType, ProductType
    order = await execution.place_order(
        instrument="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        product=ProductType.MIS,
    )
    assert order is not None
    assert order.quantity == 10
    health = await execution.health()
    assert health["paper_trading"] is True
    await execution.stop()


@pytest.mark.asyncio
async def test_execution_paper_trading(execution: ExecutionAgent):
    await execution.start()
    from src.schemas.events import OrderSide, OrderType, ProductType
    await execution.place_order(
        instrument="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        product=ProductType.MIS,
    )
    health = await execution.health()
    assert health["filled_orders"] >= 1
    await execution.stop()


@pytest.mark.asyncio
async def test_agent_emits_periodic_health_heartbeats(monkeypatch):
    monkeypatch.setenv("TRA_AGENT_HEARTBEAT_SECONDS", "0.01")
    store = InMemoryEventStore()
    agent = MarketIntelAgent(event_store=store)

    await agent.start(run_background_loop=False)
    await asyncio.sleep(0.05)

    events = await store.read("events.bus")
    health_events = [
        event for event in events
        if event.event_type.value == "system.health"
        and event.data.get("component") == "market_intel"
    ]

    assert len(health_events) >= 2

    await agent.stop()
