from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.personas import ExpertPersonasAgent
from src.agents.strategy_gen import StrategyGenAgent
from src.connectors.alternative_data import AlternativeDataProvider
from src.event_store.memory import InMemoryEventStore
from src.schemas.events import EventType, Exchange, MacroSentimentEvent, TickEvent


@pytest.mark.asyncio
async def test_alternative_data_provider_fetch():
    mock_feed = MagicMock()
    mock_entry1 = MagicMock()
    mock_entry1.title = "Market hits record high"
    mock_entry1.summary = "Bulls are in control."
    mock_entry2 = MagicMock()
    mock_entry2.title = "Oil prices surge"
    mock_entry2.summary = "Geopolitical tensions rise."
    mock_feed.entries = [mock_entry1, mock_entry2]

    provider = AlternativeDataProvider(rss_urls=["http://test-rss.com"])

    with patch("feedparser.parse", return_value=mock_feed):
        news = await provider.fetch_latest_news()
        assert "Market hits record high" in news
        assert "Oil prices surge" in news


@pytest.mark.asyncio
async def test_personas_agent_fallback_no_api_key():
    event_store = InMemoryEventStore()
    await event_store.connect()

    # Create agent with no API key
    agent = ExpertPersonasAgent(event_store=event_store, api_key="")
    await agent.start()
    assert agent.status.value == "running"

    mock_alt_data = AsyncMock()
    mock_alt_data.fetch_latest_news.return_value = "Normal news"
    agent._alt_data = mock_alt_data

    # We manually trigger evaluate to test it synchronously
    await agent._evaluate_macro_sentiment()

    # Check if fallback event was emitted to the store
    events = [e for e in await event_store.read("events.bus") if e.event_type == EventType.MACRO_SENTIMENT]
    assert len(events) == 1
    assert events[0].data["composite_multiplier"] == 1.0
    assert "Fallback" in events[0].data["rationale"]

    await agent.stop()


@pytest.mark.asyncio
async def test_personas_agent_gemini_api_success():
    event_store = InMemoryEventStore()
    await event_store.connect()

    agent = ExpertPersonasAgent(event_store=event_store, api_key="fake-api-key")
    await agent.start()

    mock_alt_data = AsyncMock()
    mock_alt_data.fetch_latest_news.return_value = "Surging growth in India!"
    agent._alt_data = mock_alt_data

    # Mock Gemini HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{\n  "geopolitical_score": 0.2,\n  "macro_score": 0.8,\n  "composite_multiplier": 1.2,\n  "rationale": "High domestic demand outweighs geopolitical risks."\n}'
                }]
            }
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await agent._evaluate_macro_sentiment()

    events = [e for e in await event_store.read("events.bus") if e.event_type == EventType.MACRO_SENTIMENT]
    assert len(events) == 1
    assert events[0].data["composite_multiplier"] == 1.2
    assert events[0].data["geopolitical_score"] == 0.2
    assert events[0].data["macro_score"] == 0.8

    await agent.stop()


@pytest.mark.asyncio
async def test_strategy_gen_receives_macro_multiplier():
    event_store = InMemoryEventStore()
    await event_store.connect()

    strategy_gen = StrategyGenAgent(event_store=event_store)
    await strategy_gen.start(run_background_loop=False)

    # Emit a macro sentiment event
    macro_event = MacroSentimentEvent.create(
        geopolitical_score=0.1,
        macro_score=0.5,
        composite_multiplier=1.5,
        rationale="Strong macro trend."
    )

    # Pass event directly to strategy_gen
    await strategy_gen.on_event(macro_event)

    assert strategy_gen._current_macro_multiplier == 1.5

    # Now verify it's applied in signal evaluation
    # Let's register a mock strategy that outputs a fixed long signal
    mock_strategy = MagicMock()
    mock_strategy.name = "mock_strat"
    mock_strategy.data_type = "tick"
    mock_strategy.evaluate = AsyncMock(return_value={
        "direction": "long",
        "confidence": 0.5,
        "features": {}
    })

    strategy_gen.register_strategy(mock_strategy, weight=1.0)

    # Force process a mock tick event
    tick = TickEvent.create(
        instrument="RELIANCE",
        exchange=Exchange.NSE,
        last_price=2500.0,
        volume=100
    )

    # We want to trace output signals, so we can mock emit or subscribe to signals
    signals_received = []
    async def mock_emit(event):
        if event.event_type == EventType.SIGNAL:
            signals_received.append(event)

    strategy_gen.emit = mock_emit

    # Process tick
    await strategy_gen._process_tick(tick)

    # The default threshold is 0.3.
    # Base vote: weight(1.0) * dir(1.0) * confidence(0.5) = 0.5
    # scaled by composite_multiplier(1.5) = 0.75
    # Since 0.75 >= threshold (0.3), it generates a signal
    assert len(signals_received) == 1
    assert signals_received[0].confidence == 0.75 # min(0.75, 0.95)
    assert signals_received[0].data["features"]["net_signal"] == 0.75

    await strategy_gen.stop()
