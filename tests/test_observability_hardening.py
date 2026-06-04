import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from src.event_store.async_bus import AsyncEventBus
from src.monitoring.metrics import MetricsCollector
from src.schemas.events import Event, EventMetadata, EventType


class _AsyncAppendStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.events: list[tuple[str, Event]] = []

    async def append(self, stream: str, event: Event) -> int:
        if self.fail:
            raise RuntimeError("append failed")
        self.events.append((stream, event))
        return len(self.events)


def _event() -> Event:
    return Event(
        event_type=EventType.TICK,
        stream="tick.NSE.TEST",
        data={"instrument": "TEST", "last_price": 100.0},
        metadata=EventMetadata(producer="test"),
    )


def _system_with_broker(broker):
    return SimpleNamespace(execution=SimpleNamespace(_broker=broker))


def test_broker_connected_metric_accepts_property_state():
    metrics = MetricsCollector()
    broker = SimpleNamespace(is_connected=True)

    text = metrics.prometheus_text(_system_with_broker(broker))

    assert "trading_broker_connected 1" in text


def test_broker_connected_metric_accepts_client_property_state():
    metrics = MetricsCollector()
    broker = SimpleNamespace(_client=SimpleNamespace(is_connected=True))

    text = metrics.prometheus_text(_system_with_broker(broker))

    assert "trading_broker_connected 1" in text


def test_broker_connected_metric_accepts_method_state():
    metrics = MetricsCollector()
    broker = SimpleNamespace(is_connected=lambda: True)

    text = metrics.prometheus_text(_system_with_broker(broker))

    assert "trading_broker_connected 1" in text


@pytest.mark.asyncio
async def test_async_bus_tracks_and_drains_persistence_tasks():
    bus = AsyncEventBus()
    bus._subscribers.clear()
    bus._persistence_tasks.clear()
    bus._persistence_errors = 0
    store = _AsyncAppendStore()
    bus.set_event_store(store)

    await bus.publish(_event())
    drained = await bus.drain_persistence_tasks(timeout=1.0)

    assert drained is True
    assert bus.persistence_pending == 0
    assert bus.persistence_errors == 0
    assert len(store.events) == 1
    assert store.events[0][0] == "events.bus"

    bus.set_event_store(None)


@pytest.mark.asyncio
async def test_async_bus_counts_persistence_errors():
    bus = AsyncEventBus()
    bus._subscribers.clear()
    bus._persistence_tasks.clear()
    bus._persistence_errors = 0
    bus.set_event_store(_AsyncAppendStore(fail=True))

    await bus.publish(_event())
    drained = await bus.drain_persistence_tasks(timeout=1.0)

    assert drained is True
    assert bus.persistence_pending == 0
    assert bus.persistence_errors == 1

    bus.set_event_store(None)


@pytest.mark.asyncio
async def test_postgres_connect_is_idempotent(monkeypatch):
    fake_asyncpg = types.SimpleNamespace(Pool=object, Record=dict, create_pool=None)
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
    postgres_module = importlib.import_module("src.event_store.postgres")

    class FakeConnection:
        def __init__(self):
            self.statements: list[str] = []

        async def execute(self, statement: str):
            self.statements.append(statement)

    class FakeAcquire:
        def __init__(self, connection: FakeConnection):
            self.connection = connection

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def __init__(self):
            self.connection = FakeConnection()
            self.closed = False

        def acquire(self):
            return FakeAcquire(self.connection)

        def is_closing(self) -> bool:
            return self.closed

        async def close(self):
            self.closed = True

    pools: list[FakePool] = []

    async def fake_create_pool(*args, **kwargs):
        pool = FakePool()
        pools.append(pool)
        return pool

    monkeypatch.setattr(postgres_module.asyncpg, "create_pool", fake_create_pool)

    store = postgres_module.PostgresEventStore("postgresql+asyncpg://user:pass@localhost/db")
    await store.connect()
    await store.connect()

    assert len(pools) == 1
    assert pools[0].connection.statements

    await store.disconnect()
