
import pytest

from src.agents.regime import RegimeDetectionAgent
from src.agents.strategy_gen import StrategyGenAgent
from src.schemas.events import Event, EventType, Exchange


@pytest.mark.asyncio
async def test_regime_detection_and_reweighting():
    from src.event_store.memory import InMemoryEventStore
    es = InMemoryEventStore()
    await es.connect()

    regime_agent = RegimeDetectionAgent(event_store=es, window=5)
    strat_agent = StrategyGenAgent(event_store=es)

    # Wire them up
    regime_agent.system = None
    strat_agent.system = None

    await regime_agent.start(run_background_loop=False)
    await strat_agent.start(run_background_loop=False)

    # 1. Test initial regime
    assert regime_agent._current_regime == "mean_reverting"

    # 2. Inject trending up ticks via OHLCV
    # To trigger trending up: price needs to go up steadily and trend_strength > 25
    # Let's inject 10 ticks going up
    from src.schemas.events import OHLCVEvent
    from datetime import datetime, timezone, timedelta
    base_time = datetime.now(timezone.utc)
    for i in range(12):
        close_price = 100.0 + i * 2.0
        event = OHLCVEvent.create(
            instrument="RELIANCE",
            exchange=Exchange.NSE,
            interval="minute",
            open=close_price - 1.0,
            high=close_price + 0.5,
            low=close_price - 0.5,
            close=close_price,
            volume=5000.0,
            producer="test"
        )
        event.timestamp = base_time + timedelta(seconds=i * 60)
        await regime_agent.on_event(event)

    # Check if regime changed
    assert regime_agent._current_regime == "trending_up"

    from src.schemas.events import EventMetadata
    event_change = Event(
        event_type=EventType.SYSTEM_STATE,
        stream="system.state",
        data={"regime": "trending_up"},
        metadata=EventMetadata(producer="regime_detection")
    )

    # Seed weights first
    strat_agent._strategy_weights = {
        "momentum": 0.2,
        "mean_reversion": 0.2,
    }

    await strat_agent.on_event(event_change)

    # Momentum weight should scale up, mean_reversion should scale down
    # (Values are normalized to sum to 1.0)
    assert strat_agent._strategy_weights["momentum"] == pytest.approx(10/11)
    assert strat_agent._strategy_weights["mean_reversion"] == pytest.approx(1/11)
