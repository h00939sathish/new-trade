import pytest

from src.agents.portfolio import PortfolioOptimizationAgent
from src.event_store.memory import InMemoryEventStore
from src.schemas.events import (
    Event,
    EventMetadata,
    EventType,
)


@pytest.fixture
def portfolio():
    store = InMemoryEventStore()
    return PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)


@pytest.mark.asyncio
async def test_start_stop(portfolio: PortfolioOptimizationAgent):
    await portfolio.start()
    assert portfolio.status.value == "running"
    health = await portfolio.health()
    assert health["capital"] == 1_000_000.0
    assert health["pnl"] == 0.0
    await portfolio.stop()
    assert portfolio.status.value == "stopped"


class TestPositionTracking:
    @pytest.mark.asyncio
    async def test_buy_fill(self):
        store = InMemoryEventStore()
        await store.connect()
        p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
        await p.event_store.connect()
        event = Event(
            event_type=EventType.FILL,
            stream="fill.RELIANCE",
            data={
                "instrument": "RELIANCE",
                "side": "buy",
                "fill_quantity": 10,
                "fill_price": 2500.0,
            },
            metadata=EventMetadata(producer="execution"),
        )
        await p._on_fill(event)
        pos = p.get_position("RELIANCE")
        assert pos["quantity"] == 10
        assert pos["avg_cost"] == 2500.0
        await p.event_store.disconnect()

    @pytest.mark.asyncio
    async def test_sell_fill(self):
        store = InMemoryEventStore()
        await store.connect()
        p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
        await p.event_store.connect()
        buy = Event(
            event_type=EventType.FILL,
            stream="fill.RELIANCE",
            data={
                "instrument": "RELIANCE",
                "side": "buy",
                "fill_quantity": 10,
                "fill_price": 2500.0,
            },
            metadata=EventMetadata(producer="execution"),
        )
        sell = Event(
            event_type=EventType.FILL,
            stream="fill.RELIANCE",
            data={
                "instrument": "RELIANCE",
                "side": "sell",
                "fill_quantity": 5,
                "fill_price": 2600.0,
            },
            metadata=EventMetadata(producer="execution"),
        )
        await p._on_fill(buy)
        await p._on_fill(sell)
        pos = p.get_position("RELIANCE")
        assert pos["quantity"] == 5
        health = await p.health()
        assert health["pnl"] == 500.0
        await p.event_store.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_instruments(self):
        store = InMemoryEventStore()
        await store.connect()
        p = PortfolioOptimizationAgent(initial_capital=1_000_000.0, event_store=store)
        await p.event_store.connect()
        await p._on_fill(Event(
            event_type=EventType.FILL, stream="fill.A",
            data={"instrument": "A", "side": "buy", "fill_quantity": 5, "fill_price": 100.0},
            metadata=EventMetadata(producer="execution"),
        ))
        await p._on_fill(Event(
            event_type=EventType.FILL, stream="fill.B",
            data={"instrument": "B", "side": "buy", "fill_quantity": 3, "fill_price": 200.0},
            metadata=EventMetadata(producer="execution"),
        ))
        assert p.get_position("A")["quantity"] == 5
        assert p.get_position("B")["quantity"] == 3
        await p.event_store.disconnect()


class TestSignalHandling:
    @pytest.mark.asyncio
    async def test_kelly_below_50_returns_zero(self):
        p = PortfolioOptimizationAgent()
        await p.event_store.connect()
        event = Event(
            event_type=EventType.SIGNAL,
            stream="signal.momentum.RELIANCE",
            data={
                "instrument": "RELIANCE",
                "direction": "long",
                "confidence": 0.4,
            },
            metadata=EventMetadata(producer="strategy_gen"),
        )
        await p._on_signal(event)
        assert p._kelly_fractions.get("RELIANCE", 0) == 0.0
        await p.event_store.disconnect()

    @pytest.mark.asyncio
    async def test_kelly_positive(self):
        p = PortfolioOptimizationAgent()
        await p.event_store.connect()
        event = Event(
            event_type=EventType.SIGNAL,
            stream="signal.momentum.TEST",
            data={
                "instrument": "TEST",
                "direction": "long",
                "confidence": 0.75,
            },
            metadata=EventMetadata(producer="strategy_gen"),
        )
        await p._on_signal(event)
        kelly = p._kelly_fractions.get("TEST", 0)
        assert 0 < kelly <= 0.25
        await p.event_store.disconnect()

    @pytest.mark.asyncio
    async def test_kelly_caps_at_25_percent(self):
        p = PortfolioOptimizationAgent()
        await p.event_store.connect()
        for direction in ("long", "short"):
            event = Event(
                event_type=EventType.SIGNAL,
                stream="signal.momentum.TEST",
                data={
                    "instrument": "TEST",
                    "direction": direction,
                    "confidence": 1.0,
                },
                metadata=EventMetadata(producer="strategy_gen"),
            )
            await p._on_signal(event)
        assert p._kelly_fractions.get("TEST", 0) == 0.25
        await p.event_store.disconnect()


class TestKellyMath:
    def test_below_50(self):
        p = PortfolioOptimizationAgent()
        assert p._kelly_fraction(0.4, "long") == 0.0
        assert p._kelly_fraction(0.5, "long") == 0.0

    def test_fractional_kelly(self):
        p = PortfolioOptimizationAgent()
        f = p._kelly_fraction(0.75, "long")
        assert f == 0.125

    def test_high_confidence(self):
        p = PortfolioOptimizationAgent()
        f = p._kelly_fraction(0.9, "long")
        assert 0 < f <= 0.25
        assert f == pytest.approx(0.2, abs=0.001)


class TestHealthCapital:
    @pytest.mark.asyncio
    async def test_initial_values(self):
        p = PortfolioOptimizationAgent(initial_capital=500_000.0)
        await p.event_store.connect()
        health = await p.health()
        assert health["capital"] == 500_000.0
        assert health["pnl"] == 0.0
        assert health["open_positions"] == 0
        assert health["total_exposure"] == 0.0
        await p.event_store.disconnect()

    @pytest.mark.asyncio
    async def test_after_fill(self):
        p = PortfolioOptimizationAgent(initial_capital=500_000.0)
        await p.event_store.connect()
        await p._on_fill(Event(
            event_type=EventType.FILL, stream="fill.TEST",
            data={"instrument": "TEST", "side": "buy", "fill_quantity": 10, "fill_price": 100.0},
            metadata=EventMetadata(producer="execution"),
        ))
        health = await p.health()
        assert health["open_positions"] == 1
        assert health["total_exposure"] == 1000.0
        await p.event_store.disconnect()
