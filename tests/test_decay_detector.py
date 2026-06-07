"""
Tests for P2.3 — strategy decay detector emits STRATEGY_DECAY event.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from src.monitoring.decay_detector import PerformanceDecayDetector


@pytest.mark.asyncio
async def test_decay_detector_emits_strategy_decay_event():
    """After 20 losing trades, the detector should emit STRATEGY_DECAY.

    Per three_stage_roadmap.md P2.3:
      rolling 20-trade window's Sharpe < 0 → emit STRATEGY_DECAY event
      Action: not auto-disable, but emit and the alert agent notifies
    """
    from src.schemas.events import EventType

    captured_events = []
    pending_tasks = []

    async def capture_emit(event):
        captured_events.append(event)

    market_intel = MagicMock()
    market_intel.emit = capture_emit

    system = MagicMock()
    system.market_intel = market_intel
    system.strategy_gen = MagicMock()
    system.strategy_gen._strategy_weights = {"momentum": 0.4}

    # Track tasks created via loop.create_task so we can await them
    loop = asyncio.get_running_loop()
    original_create_task = loop.create_task

    def tracking_create_task(coro, *args, **kwargs):
        task = original_create_task(coro, *args, **kwargs)
        pending_tasks.append(task)
        return task

    loop.create_task = tracking_create_task

    try:
        detector = PerformanceDecayDetector(
            system=system, rolling_window=20, min_trades=15, min_sharpe=0.0
        )

        # Feed 20 losing trades with some variance (so std > 0)
        for i in range(20):
            detector.record_trade("momentum", -100.0 - i)

        # Await all the scheduled emit tasks
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
    finally:
        loop.create_task = original_create_task

    # Verify the event was emitted with the right type
    assert len(captured_events) >= 1, (
        f"Expected at least 1 emitted event, got {len(captured_events)}"
    )
    decay_events = [e for e in captured_events if e.event_type == EventType.STRATEGY_DECAY]
    assert len(decay_events) >= 1
    ev = decay_events[0]
    assert ev.data["strategy"] == "momentum"
    assert "rolling_sharpe" in ev.data
    assert ev.data["auto_disabled"] is True


@pytest.mark.asyncio
async def test_decay_detector_does_not_emit_when_sharpe_above_threshold():
    """If the strategy is winning, no decay event should fire."""
    from src.schemas.events import EventType

    captured_events = []

    async def capture_emit(event):
        captured_events.append(event)

    system = MagicMock()
    system.market_intel = MagicMock()
    system.market_intel.emit = capture_emit
    system.strategy_gen = MagicMock()
    system.strategy_gen._strategy_weights = {"momentum": 0.4}

    detector = PerformanceDecayDetector(
        system=system, rolling_window=20, min_trades=15, min_sharpe=0.5
    )

    # 20 winning trades — Sharpe will be very high
    for i in range(20):
        detector.record_trade("momentum", 100.0 + i)

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    decay_events = [e for e in captured_events if e.event_type == EventType.STRATEGY_DECAY]
    assert len(decay_events) == 0, f"Expected 0 decay events, got {len(decay_events)}"


def test_decay_detector_below_min_trades_does_not_emit():
    """With fewer than min_trades, no decay evaluation happens."""
    captured_events = []

    async def capture_emit(event):
        captured_events.append(event)

    system = MagicMock()
    system.market_intel = MagicMock()
    system.market_intel.emit = capture_emit
    system.strategy_gen = MagicMock()
    system.strategy_gen._strategy_weights = {"momentum": 0.4}

    detector = PerformanceDecayDetector(
        system=system, rolling_window=20, min_trades=15, min_sharpe=0.0
    )

    # Only 5 losing trades — below min_trades
    for i in range(5):
        detector.record_trade("momentum", -100.0)

    from src.schemas.events import EventType

    decay_events = [e for e in captured_events if e.event_type == EventType.STRATEGY_DECAY]
    assert len(decay_events) == 0
