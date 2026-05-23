import pytest

from src.agents.risk_mgmt import RiskManagementAgent
from src.schemas.events import Event, EventMetadata, EventType


@pytest.fixture
def risk():
    return RiskManagementAgent()


@pytest.mark.asyncio
async def test_var_check_insufficient_data(risk: RiskManagementAgent):
    await risk.start()
    result = await risk._check_var_risk("TEST")
    assert result["name"] == "var_95"
    assert result["passed"] is True
    assert "insufficient data" in str(result["details"].get("reason", ""))
    await risk.stop()


@pytest.mark.asyncio
async def test_var_check_with_price_data(risk: RiskManagementAgent):
    await risk.start()
    for price in [100.0 + i for i in range(30)]:
        tick = Event(
            event_type=EventType.TICK,
            stream="test",
            data={"instrument": "TEST", "last_price": price},
            metadata=EventMetadata(producer="test"),
        )
        risk._track_price(tick)
    result = await risk._check_var_risk("TEST")
    assert result["name"] == "var_95"
    await risk.stop()


@pytest.mark.asyncio
async def test_drawdown_check_no_data(risk: RiskManagementAgent):
    await risk.start()
    result = await risk._check_drawdown_risk()
    assert result["passed"] is True
    assert "no portfolio data" in str(result["details"].get("reason", ""))
    await risk.stop()


@pytest.mark.asyncio
async def test_instrument_exposure_check(risk: RiskManagementAgent):
    await risk.start()
    result = await risk._check_instrument_risk("TEST", "long", 0.8)
    assert result["name"] == "instrument_exposure"
    assert result["passed"] is True
    await risk.stop()
