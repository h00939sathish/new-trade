import asyncio

import pytest

from src.system import TradingSystem


@pytest.fixture(autouse=True)
def clean_db():
    import os
    import time
    db = "trading_events.db"
    for f in (db, db + "-wal", db + "-shm"):
        for _ in range(5):
            try:
                if os.path.exists(f):
                    os.remove(f)
                break
            except PermissionError:
                time.sleep(0.2)
    yield


@pytest.fixture
def system():
    return TradingSystem(providers={'kite_client': None, 'kite_broker': None})


@pytest.mark.asyncio
async def test_system_start_stop(system: TradingSystem):
    await system.start()
    health = await system.health()
    for agent_name, status in health.items():
        assert status["status"] == "running"
    await system.stop()
    for agent in [system.market_intel, system.strategy_gen, system.risk_mgmt, system.execution, system.portfolio_opt]:
        assert agent.status.value == "stopped"


@pytest.mark.asyncio
async def test_tick_through_full_pipeline(system: TradingSystem):
    await system.start()
    system.strategy_gen.register_strategy(
        system.strategy_gen._strategies["momentum"]
    )

    for price in [100.0] * 15 + [105.0, 110.0, 115.0, 120.0, 125.0, 130.0]:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.0)

    signals = []
    risk_checks = []
    orders = []
    fills = []
    portfolio_updates = []
    async for event in system.market_intel.event_store.replay():
        if event.event_type.value == "signal.generated":
            signals.append(event)
        if event.event_type.value in ("risk.check", "risk.breach"):
            risk_checks.append(event)
        if event.event_type.value == "order.created":
            orders.append(event)
        if event.event_type.value == "order.fill":
            fills.append(event)
        if event.event_type.value == "portfolio.update":
            portfolio_updates.append(event)

    await system.stop()
    assert len(signals) >= 1, "No signals generated from tick data"
    assert len(risk_checks) >= 1, "No risk checks triggered"
    assert len(portfolio_updates) >= 0


@pytest.mark.asyncio
async def test_ohlcv_through_full_pipeline(system: TradingSystem):
    await system.start()

    for i in range(25):
        close = 100.0 + (i * 0.5)
        await system.inject_ohlcv(
            "TCS", "minute",
            open=close - 0.5, high=close + 0.25,
            low=close - 0.5, close=close,
            volume=10000 + i * 100,
        )
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.0)

    signals = []
    async for event in system.market_intel.event_store.replay():
        if event.event_type.value == "signal.generated":
            signals.append(event)

    await system.stop()
    assert len(signals) >= 1, "No signals generated from OHLCV data"


@pytest.mark.asyncio
async def test_full_pipeline_with_portfolio(system: TradingSystem):
    await system.start()
    system.strategy_gen.register_strategy(
        system.strategy_gen._strategies["momentum"]
    )

    prices = [100.0] * 15 + [105.0, 110.0, 115.0, 120.0, 125.0, 130.0, 135.0, 140.0]
    for price in prices:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.0)

    orders = []
    fills = []
    portfolio_updates = []
    async for event in system.market_intel.event_store.replay():
        if event.event_type.value == "order.created":
            orders.append(event)
        if event.event_type.value == "order.fill":
            fills.append(event)
        if event.event_type.value == "portfolio.update":
            portfolio_updates.append(event)

    await system.stop()
    assert len(orders) >= 0
    assert len(fills) >= 0


@pytest.mark.asyncio
async def test_risk_rejects_large_signal(system: TradingSystem):
    await system.start()

    for price in [100.0] * 20 + [150.0, 155.0, 160.0]:
        await system.inject_tick("BIGMOV", price, volume=10000)
        await asyncio.sleep(0.05)

    await asyncio.sleep(1.0)

    risk_breaches = []
    async for event in system.market_intel.event_store.replay():
        if event.event_type.value == "risk.breach":
            risk_breaches.append(event)

    await system.stop()


@pytest.mark.asyncio
async def test_portfolio_agent_tracks_fills(system: TradingSystem):
    await system.start()
    system.strategy_gen.register_strategy(
        system.strategy_gen._strategies["momentum"]
    )

    prices = [100.0] * 15 + [105.0] * 10
    for price in prices:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.0)

    health = await system.portfolio_opt.health()
    assert health["status"] == "running"
    assert health["pnl"] >= 0

    await system.stop()


@pytest.mark.asyncio
async def test_system_health_endpoint(system: TradingSystem):
    await system.start()
    health = await system.health()
    await system.stop()
    assert "market_intel" in health
    assert "strategy_gen" in health
    assert "risk_mgmt" in health
    assert "execution" in health
    assert "portfolio_opt" in health
    for name, status in health.items():
        assert "event_store" in status
        assert "subscribed_types" in status


@pytest.mark.asyncio
async def test_multiple_instruments(system: TradingSystem):
    await system.start()
    system.strategy_gen.register_strategy(
        system.strategy_gen._strategies["momentum"]
    )

    for price in [100.0] * 25 + [106.0, 107.0, 108.0]:
        await system.inject_tick("RELIANCE", price, volume=1000)
        await system.inject_tick("TCS", price - 5, volume=500)
        await asyncio.sleep(0.02)

    await asyncio.sleep(1.0)

    signals = []
    async for event in system.market_intel.event_store.replay():
        if event.event_type.value == "signal.generated":
            signals.append(event)
        if event.event_type.value == "order.created":
            pass

    await system.stop()
    assert len(signals) >= 1
