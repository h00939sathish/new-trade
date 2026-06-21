import pytest

from src.risk.kill_switch import KillSwitch


@pytest.fixture(autouse=True)
def reset_kill_switch():
    KillSwitch.reset_singleton()
    from pathlib import Path
    state_file = Path("state/kill_switch.state")
    if state_file.exists():
        state_file.unlink()
    yield
    KillSwitch.reset_singleton()
    if state_file.exists():
        state_file.unlink()


@pytest.mark.asyncio
async def test_trigger_via_drawdown():
    ks = KillSwitch()
    ks.setup(daily_loss_pct=0.01, max_drawdown_pct=0.05, initial_capital=100_000.0)
    triggered = await ks.check_limits(
        current_capital=80_000.0, current_pnl=0.0, peak_capital=100_000.0
    )
    assert triggered is True
    assert ks.active is True
    assert "Drawdown" in ks.reason


@pytest.mark.asyncio
async def test_trigger_via_daily_loss():
    ks = KillSwitch()
    ks.setup(daily_loss_pct=0.01, max_drawdown_pct=0.05, initial_capital=100_000.0)
    triggered = await ks.check_limits(
        current_capital=100_000.0, current_pnl=-5_000.0, peak_capital=100_000.0
    )
    assert triggered is True
    assert ks.active is True
    assert "loss" in ks.reason.lower()


@pytest.mark.asyncio
async def test_no_trigger_within_limits():
    ks = KillSwitch()
    ks.setup(daily_loss_pct=0.01, max_drawdown_pct=0.05, initial_capital=100_000.0)
    triggered = await ks.check_limits(
        current_capital=98_000.0, current_pnl=-500.0, peak_capital=100_000.0
    )
    assert triggered is False
    assert ks.active is False


@pytest.mark.asyncio
async def test_persist_and_restore(tmp_path):
    import json

    state_file = tmp_path / "kill_switch.state"
    import src.risk.kill_switch as ks_mod

    ks_mod._KILL_SWITCH_STATE_PATH = state_file

    ks1 = KillSwitch()
    ks1.setup(daily_loss_pct=0.01, max_drawdown_pct=0.05, initial_capital=100_000.0)
    await ks1.trigger("test_persist")
    assert ks1.active is True

    KillSwitch.reset_singleton()
    state_file.write_text(json.dumps({"active": True, "reason": "test_persist", "auto_reset": False}))
    ks2 = KillSwitch()
    assert ks2.active is True
    assert ks2.reason == "test_persist"


@pytest.mark.asyncio
async def test_auto_reset_default_is_false():
    ks = KillSwitch()
    assert ks._auto_reset is False


@pytest.mark.asyncio
async def test_concurrent_triggers_produce_one_flatten():
    ks = KillSwitch()
    ks.setup(daily_loss_pct=0.01, max_drawdown_pct=0.05, initial_capital=100_000.0)
    import asyncio

    tasks = [ks.trigger(f"concurrent_{i}") for i in range(10)]
    await asyncio.gather(*tasks)
    assert ks.active is True


@pytest.mark.asyncio
async def test_reset_clears_state():
    ks = KillSwitch()
    ks.setup(daily_loss_pct=0.01, max_drawdown_pct=0.05, initial_capital=100_000.0)
    await ks.trigger("test_reset")
    assert ks.active is True
    ks.reset()
    assert ks.active is False
    assert ks.reason == ""


@pytest.mark.asyncio
async def test_daily_auto_reset_does_not_fire_when_disabled():
    ks = KillSwitch()
    ks._auto_reset = False
    await ks.trigger("test_daily_reset")
    assert ks.active is True
    ks.daily_auto_reset()
    assert ks.active is True
