
import pytest

from src.event_store.memory import InMemoryEventStore
from src.event_store.sqlite import SqliteEventStore
from src.schemas.events import (
    EventType,
    Exchange,
    FillEvent,
    OHLCVEvent,
    OrderEvent,
    OrderSide,
    OrderType,
    ProductType,
    RiskCheckEvent,
    SignalEvent,
    SystemEvent,
    TickEvent,
)


@pytest.fixture
def event_store():
    store = InMemoryEventStore()
    return store


@pytest.fixture
def sqlite_store(tmp_path):
    db_path = tmp_path / "test_events.db"
    store = SqliteEventStore(db_path)
    return store


@pytest.mark.asyncio
async def test_append_and_read(event_store: InMemoryEventStore):
    await event_store.connect()
    event = TickEvent.create("RELIANCE", Exchange.NSE, 2500.0)
    pos = await event_store.append("tick.NSE.RELIANCE", event)
    assert pos > 0
    events = await event_store.read("tick.NSE.RELIANCE")
    assert len(events) == 1
    assert events[0].data["instrument"] == "RELIANCE"
    assert events[0].data["last_price"] == 2500.0
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_replay_all_events(event_store: InMemoryEventStore):
    await event_store.connect()
    events_to_add = [
        TickEvent.create("RELIANCE", Exchange.NSE, 2500.0),
        TickEvent.create("TCS", Exchange.NSE, 3500.0),
        TickEvent.create("INFY", Exchange.NSE, 1500.0),
    ]
    for e in events_to_add:
        await event_store.append("tick.NSE", e)
    replayed = []
    async for event in event_store.replay():
        replayed.append(event)
    assert len(replayed) == 3


@pytest.mark.asyncio
async def test_get_latest(event_store: InMemoryEventStore):
    await event_store.connect()
    e1 = TickEvent.create("RELIANCE", Exchange.NSE, 2500.0)
    e2 = TickEvent.create("RELIANCE", Exchange.NSE, 2510.0)
    await event_store.append("tick.NSE.RELIANCE", e1)
    await event_store.append("tick.NSE.RELIANCE", e2)
    latest = await event_store.get_latest("tick.NSE.RELIANCE")
    assert latest is not None
    assert latest.data["last_price"] == 2510.0
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_tick_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = TickEvent.create("AAPL", Exchange.NSE, 150.25, volume=1000, bid=150.20, ask=150.30)
    assert event.event_type == EventType.TICK
    assert event.instrument == "AAPL"
    assert event.last_price == 150.25
    assert event.volume == 1000
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_ohlcv_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = OHLCVEvent.create("RELIANCE", Exchange.NSE, "minute", 100, 110, 99, 105, 10000, oi=5000)
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    events = await event_store.read(event.stream)
    assert len(events) == 1
    assert events[0].data["high"] == 110
    assert events[0].data["oi"] == 5000
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_signal_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = SignalEvent.create(
        "RELIANCE", "momentum", "long", 0.85, price=2500.0,
        features={"rsi": 65, "ma_cross": True},
    )
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert event.direction == "long"
    assert event.confidence == 0.85
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_order_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = OrderEvent.create(
        "RELIANCE", Exchange.NSE, OrderSide.BUY, OrderType.LIMIT,
        10, ProductType.MIS, price=2500.0,
    )
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert event.side == OrderSide.BUY
    assert event.quantity == 10
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_fill_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = FillEvent.create(
        order_id="test_order_1",
        instrument="RELIANCE",
        exchange=Exchange.NSE,
        side=OrderSide.BUY,
        fill_price=2500.0,
        fill_quantity=10,
    )
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert event.fill_price == 2500.0
    assert event.fill_quantity == 10
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_risk_check_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = RiskCheckEvent.create(
        "position_limit", True, instrument="RELIANCE",
        details={"current": 50, "limit": 100},
    )
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert event.passed
    assert event.check_name == "position_limit"
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_risk_breach_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = RiskCheckEvent.create(
        "drawdown_limit", False,
        details={"drawdown": 0.2, "limit": 0.15},
    )
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert not event.passed
    assert event.event_type == EventType.RISK_BREACH
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_system_health_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = SystemEvent.health("market_intel", "running", {"uptime": 3600})
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert event.data["component"] == "market_intel"
    assert event.data["status"] == "running"
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_system_error_event(event_store: InMemoryEventStore):
    await event_store.connect()
    event = SystemEvent.error("execution", "Connection timeout", fatal=False)
    pos = await event_store.append(event.stream, event)
    assert pos > 0
    assert event.data["component"] == "execution"
    assert not event.data["fatal"]
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_append_batch(event_store: InMemoryEventStore):
    await event_store.connect()
    events = [
        TickEvent.create("RELIANCE", Exchange.NSE, 2500.0),
        TickEvent.create("RELIANCE", Exchange.NSE, 2505.0),
        TickEvent.create("RELIANCE", Exchange.NSE, 2510.0),
    ]
    positions = await event_store.append_batch("tick.NSE.RELIANCE", events)
    assert len(positions) == 3
    assert positions[2] > positions[1] > positions[0]
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_stream_names(event_store: InMemoryEventStore):
    await event_store.connect()
    await event_store.append("stream.a", TickEvent.create("RELIANCE", Exchange.NSE, 100))
    await event_store.append("stream.b", TickEvent.create("TCS", Exchange.NSE, 200))
    names = await event_store.get_stream_names()
    assert "stream.a" in names
    assert "stream.b" in names
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_stream_length(event_store: InMemoryEventStore):
    await event_store.connect()
    for i in range(5):
        await event_store.append("test", TickEvent.create("RELIANCE", Exchange.NSE, float(i)))
    length = await event_store.get_stream_length("test")
    assert length == 5
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_delete_stream(event_store: InMemoryEventStore):
    await event_store.connect()
    await event_store.append("temp", TickEvent.create("RELIANCE", Exchange.NSE, 100))
    assert await event_store.get_stream_length("temp") == 1
    await event_store.delete_stream("temp")
    assert await event_store.get_stream_length("temp") == 0
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_health_check(event_store: InMemoryEventStore):
    await event_store.connect()
    health = await event_store.health_check()
    assert health["status"] == "healthy"
    assert health["type"] == "memory"
    await event_store.disconnect()


@pytest.mark.asyncio
async def test_sqlite_event_store(sqlite_store: SqliteEventStore):
    await sqlite_store.connect()
    event = TickEvent.create("RELIANCE", Exchange.NSE, 2500.0)
    pos = await sqlite_store.append("tick.NSE.RELIANCE", event)
    assert pos > 0
    events = await sqlite_store.read("tick.NSE.RELIANCE")
    assert len(events) == 1
    assert events[0].data["instrument"] == "RELIANCE"
    await sqlite_store.disconnect()


@pytest.mark.asyncio
async def test_serialization_roundtrip(event_store: InMemoryEventStore):
    await event_store.connect()
    original = TickEvent.create("RELIANCE", Exchange.NSE, 2500.0, volume=100)
    await event_store.append("test", original)
    events = await event_store.read("test")
    restored = events[0]
    assert restored.event_id == original.event_id
    assert restored.event_type == original.event_type
    assert restored.timestamp is not None
    await event_store.disconnect()
