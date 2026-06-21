from datetime import UTC, datetime

import pytest

from src.agents.execution import ExecutionAgent
from src.agents.strategy_gen import StrategyGenAgent
from src.strategies.technical import MeanReversionStrategy, MomentumStrategy
from src.event_store.async_bus import AsyncEventBus
from src.event_store.memory import InMemoryEventStore
from src.risk.costs import TransactionCostModel
from src.schemas.events import (
    Event,
    EventMetadata,
    EventType,
)


def test_transaction_cost_model():
    model = TransactionCostModel(brokerage_pct=0.0003, slippage_bps=5.0)

    # Buy CNC
    # Quantity: 100, Price: 100.0, Product: cnc
    cost = model.total_cost("buy", 100, 100.0, product="cnc")
    assert cost > 0

    # Sell MIS
    # Quantity: 100, Price: 100.0, Product: mis
    cost_sell = model.total_cost("sell", 100, 100.0, product="mis")
    assert cost_sell > 0


def test_intelligent_position_sizing():
    agent = ExecutionAgent()

    # Capital: 100,000, Price: 100.0, Volatility (ATR): 2.0
    # Stop distance = 2 * 2.0 = 4.0
    # Risk per trade = 1% of 100,000 = 1,000
    # Raw qty = 1,000 / 4.0 = 250
    # Max qty = 5% of 100,000 / 100.0 = 5,000 / 100.0 = 50
    # Expected qty = min(250, 50) = 50
    qty = agent._calculate_quantity(0.8, 100.0, 100000.0, 2.0)
    assert qty == 50

    # Low volatility case: Volatility (ATR) = 0.1
    # Stop distance = 2 * 0.1 = 0.2
    # Risk per trade = 1,000
    # Raw qty = 1,000 / 0.2 = 5,000
    # Max qty = 50
    # Expected qty = 50
    qty_low_vol = agent._calculate_quantity(0.8, 100.0, 100000.0, 0.1)
    assert qty_low_vol == 50


@pytest.mark.asyncio
async def test_async_event_bus_routing():
    bus = AsyncEventBus()
    queue = bus.subscribe("test_agent", {EventType.TICK})

    event = Event(
        event_type=EventType.TICK,
        stream="tick.NSE.RELIANCE",
        data={"last_price": 2500.0},
        metadata=EventMetadata(producer="market_intel"),
    )
    await bus.publish(event)

    received = await queue.get()
    assert received.event_id == event.event_id


@pytest.mark.asyncio
async def test_strategy_gen_sl_tp_exits():
    store = InMemoryEventStore()
    await store.connect()
    agent = StrategyGenAgent(event_store=store)
    await agent.start(run_background_loop=False)

    # Register strategy and fake a position
    # Instrument: RELIANCE, qty: 10, avg_price: 100.0
    from src.risk.position_registry import position_registry

    position_registry.reset()
    await position_registry.update_from_fill("RELIANCE", "buy", 10, 100.0)
    await position_registry.set_sl_tp(
        "RELIANCE", stop_loss=98.0, take_profit=105.0, stop_loss_pct=0.02, take_profit_pct=0.05
    )

    # 1. Trigger Tick below Stop Loss
    tick_event = Event(
        event_type=EventType.TICK,
        stream="tick.NSE.RELIANCE",
        data={"instrument": "RELIANCE", "last_price": 97.0},
        metadata=EventMetadata(producer="market_intel"),
        timestamp=datetime.now(UTC),
    )

    # Capture emitted events
    emitted = []

    async def mock_emit(evt):
        emitted.append(evt)

    agent.emit = mock_emit

    await agent.on_event(tick_event)

    # Verify exit signal is emitted
    assert len(emitted) == 1
    exit_sig = emitted[0]
    assert exit_sig.event_type == EventType.SIGNAL
    assert exit_sig.data["direction"] == "neutral"
    assert exit_sig.data["features"]["exit_reason"] == "stop_loss"

    await agent.stop()
    await store.disconnect()


@pytest.mark.asyncio
async def test_strategy_gen_consensus_ensemble():
    store = InMemoryEventStore()
    await store.connect()

    agent = StrategyGenAgent(event_store=store)
    agent.threshold = 0.2
    agent.short_threshold = 0.2

    await agent.start(run_background_loop=False)
    agent._strategies.clear()
    agent._strategy_weights.clear()

    # Register two strategies
    strat1 = MomentumStrategy(short_window=2, long_window=5, threshold=0.01)
    strat2 = MeanReversionStrategy(window=5, entry_z=1.0)
    agent.register_strategy(strat1, weight=0.6)
    agent.register_strategy(strat2, weight=0.4)

    # Prices: [100.0, 100.0, 100.0, 100.0, 100.0, 105.0]
    # Strat1: short_ma = 102.5, long_ma = 101.0, ratio = 1.48% > 1%, direction="long", confidence=0.297
    # Strat2: mean = 101.0, std = 2.0, price = 105.0, z_score = 2.0 > 1.0, direction="short", confidence=0.95
    # Votes: Strat1 = +0.6 * 0.297 = +0.1782; Strat2 = -0.4 * 0.95 = -0.38
    # Net = -0.2018 (absolute >= 0.2, direction="short")

    emitted = []

    async def mock_emit(evt):
        emitted.append(evt)

    agent.emit = mock_emit

    for p in [100.0, 100.0, 100.0, 100.0, 100.0]:
        tick = Event(
            event_type=EventType.TICK,
            stream="tick.NSE.TEST",
            data={"instrument": "TEST", "last_price": p},
            metadata=EventMetadata(producer="market_intel"),
        )
        await agent.on_event(tick)

    tick_final = Event(
        event_type=EventType.TICK,
        stream="tick.NSE.TEST",
        data={"instrument": "TEST", "last_price": 105.0},
        metadata=EventMetadata(producer="market_intel"),
    )
    await agent.on_event(tick_final)

    assert len(emitted) >= 1
    consensus_sig = [e for e in emitted if e.data.get("strategy") == "consensus_ensemble"]
    assert len(consensus_sig) == 1
    assert consensus_sig[0].data["direction"] == "short"

    await agent.stop()
    await store.disconnect()
