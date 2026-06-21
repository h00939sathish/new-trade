import pytest

from src.risk.position_registry import PositionRegistry, position_registry


@pytest.fixture(autouse=True)
def reset_registry():
    PositionRegistry.reset_singleton()


@pytest.mark.asyncio
async def test_sl_trigger_via_strategy_gen():
    instrument = "TEST_EQ"
    await position_registry.update_from_fill(instrument, "buy", 100, 100.0)
    await position_registry.set_sl_tp(
        instrument,
        stop_loss=95.0,
        take_profit=110.0,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )
    pos = position_registry.get_position(instrument)
    assert pos["stop_loss"] == 95.0
    assert pos["take_profit"] == 110.0


@pytest.mark.asyncio
async def test_trailing_sl_updates():
    instrument = "TEST_EQ"
    await position_registry.update_from_fill(instrument, "buy", 100, 100.0)
    await position_registry.set_sl_tp(
        instrument,
        stop_loss=95.0,
        take_profit=110.0,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )
    await position_registry.update_trailing_sl(instrument, 97.0)
    pos = position_registry.get_position(instrument)
    assert pos["stop_loss"] == 97.0
    await position_registry.update_trailing_sl(instrument, 96.0)
    pos = position_registry.get_position(instrument)
    assert pos["stop_loss"] == 97.0


@pytest.mark.asyncio
async def test_sl_does_not_trigger_for_unrelated_position():
    instrument = "SL_UNRELATED_TEST"
    await position_registry.update_from_fill(instrument, "buy", 100, 100.0)
    pos = position_registry.get_position(instrument)
    assert pos["quantity"] == 100
    pos2 = position_registry.get_position("OTHER_UNRELATED")
    assert pos2["quantity"] == 0
