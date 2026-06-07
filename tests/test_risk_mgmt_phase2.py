from datetime import date

import pytest

from src.agents.risk_mgmt import RiskManagementAgent
from src.config.settings import settings
from src.risk.position_registry import position_registry
from src.schemas.events import EventType, SignalEvent


@pytest.mark.asyncio
async def test_risk_mgmt_max_open_positions():
    # Enforce maximum open positions to 1 for this test
    settings.risk_max_open_positions = 1

    agent = RiskManagementAgent()
    agent._is_market_hours = lambda *args, **kwargs: True
    agent._is_square_off_window = lambda *args, **kwargs: False

    # Emulate having an open position in RELIANCE using PositionRegistry
    position_registry.reset()
    await position_registry.update_from_fill("RELIANCE", "buy", 50, 100.0)

    # Try sending signal for TCS (new position)
    event_tcs = SignalEvent.create(
        instrument="TCS",
        strategy="momentum",
        direction="long",
        confidence=0.8,
        price=3000.0,
    )

    # Mock self.emit to catch risk event
    emitted = []

    async def mock_emit(ev):
        emitted.append(ev)

    agent.emit = mock_emit

    await agent._validate_signal(event_tcs)

    assert len(emitted) == 1
    risk_check = emitted[0]
    assert risk_check.event_type == EventType.RISK_BREACH
    # The signal should fail the risk checks because max positions is reached
    assert risk_check.data["passed"] is False
    checks = risk_check.data["details"]["checks"]
    max_pos_check = next(c for c in checks if c["name"] == "max_open_positions")
    assert max_pos_check["passed"] is False


@pytest.mark.asyncio
async def test_risk_mgmt_earnings_filter():
    agent = RiskManagementAgent()
    agent._is_market_hours = lambda *args, **kwargs: True
    agent._is_square_off_window = lambda *args, **kwargs: False

    # Mock earnings calendar filter to say TCS has earnings today
    date.today()

    class MockEarningsFilter:
        def is_near_earnings(self, symbol, d):
            return symbol == "TCS"

    agent._earnings_filter = MockEarningsFilter()

    event_tcs = SignalEvent.create(
        instrument="TCS",
        strategy="momentum",
        direction="long",
        confidence=0.8,
        price=3000.0,
    )

    emitted = []

    async def mock_emit(ev):
        emitted.append(ev)

    agent.emit = mock_emit

    await agent._validate_signal(event_tcs)

    assert len(emitted) == 1
    risk_check = emitted[0]
    assert risk_check.data["passed"] is False
    checks = risk_check.data["details"]["checks"]
    earnings_check = next(c for c in checks if c["name"] == "earnings_calendar")
    assert earnings_check["passed"] is False


@pytest.mark.asyncio
async def test_risk_mgmt_correlation_risk():
    agent = RiskManagementAgent()
    agent._is_market_hours = lambda *args, **kwargs: True
    agent._is_square_off_window = lambda *args, **kwargs: False

    # Emulate having an open position in INFY using PositionRegistry
    position_registry.reset()
    await position_registry.update_from_fill("INFY", "buy", 100, 100.0)

    # Mock system and strategy_gen to supply highly correlated returns for INFY and TCS
    class MockStrategyGen:
        def __init__(self):
            # Perfect positive correlation price series
            self._candle_prices = {
                "INFY": {"minute": [100.0 + i for i in range(40)]},
                "TCS": {"minute": [200.0 + i * 2 for i in range(40)]},
            }

    class MockSystem:
        def __init__(self):
            self.strategy_gen = MockStrategyGen()

    agent.system = MockSystem()

    event_tcs = SignalEvent.create(
        instrument="TCS",
        strategy="momentum",
        direction="long",
        confidence=0.8,
        price=4000.0,
    )

    emitted = []

    async def mock_emit(ev):
        emitted.append(ev)

    agent.emit = mock_emit

    await agent._validate_signal(event_tcs)

    assert len(emitted) == 1
    risk_check = emitted[0]
    assert risk_check.data["passed"] is False
    checks = risk_check.data["details"]["checks"]
    corr_check = next(c for c in checks if c["name"] == "correlation")
    assert corr_check["passed"] is False
