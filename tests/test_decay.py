import asyncio

import pytest

from src.agents.strategy_gen import StrategyGenAgent
from src.event_store.memory import InMemoryEventStore
from src.monitoring.decay_detector import PerformanceDecayDetector


class MockSystem:
    def __init__(self, es):
        self.market_intel = MockMarketIntel()
        self.strategy_gen = StrategyGenAgent(event_store=es)
        self.strategy_gen._strategy_weights = {
            "momentum": 1.0,
            "mean_reversion": 1.0,
        }


class MockMarketIntel:
    def __init__(self):
        self.emitted_events = []

    async def emit(self, event):
        self.emitted_events.append(event)


@pytest.mark.asyncio
async def test_performance_decay_detector():
    es = InMemoryEventStore()
    await es.connect()

    system = MockSystem(es)
    detector = PerformanceDecayDetector(
        system=system, rolling_window=5, min_trades=5, min_sharpe=0.5
    )

    # 1. Record some winning trades for 'momentum' with variance
    winning_trades = [10.0, 11.0, 9.0, 10.0, 10.0]
    for pnl in winning_trades:
        detector.record_trade("momentum", pnl)

    # Weight should still be 1.0
    assert system.strategy_gen._strategy_weights["momentum"] == 1.0

    # 2. Record some losing trades for 'momentum' with variance to trigger decay
    losing_trades = [-10.0, -11.0, -9.0, -10.0, -10.0]
    for pnl in losing_trades:
        detector.record_trade("momentum", pnl)

    # Weight should be zeroed
    assert system.strategy_gen._strategy_weights["momentum"] == 0.0

    # Give the async task a chance to run
    await asyncio.sleep(0.05)

    # System event should have been emitted
    assert len(system.market_intel.emitted_events) > 0
    decay_event = system.market_intel.emitted_events[0]
    assert decay_event.event_type.value == "strategy.decay"
    assert decay_event.data["strategy"] == "momentum"
