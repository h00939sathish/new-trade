import asyncio

import pytest

from src.event_store.memory import InMemoryEventStore
from src.monitoring.http_dashboard import HTML, HttpDashboard
from src.system import TradingSystem


@pytest.fixture
def store():
    return InMemoryEventStore()


@pytest.fixture
async def system(store):
    sys = TradingSystem(event_store=store, providers={})
    await sys.start()
    yield sys
    await sys.stop()


@pytest.mark.asyncio
async def test_dashboard_start_stop(system: TradingSystem):
    dash = HttpDashboard(system, port=18181)
    await dash.start()
    assert dash._server is not None
    await dash.stop()
    assert dash._server is not None


@pytest.mark.asyncio
async def test_dashboard_health_endpoint(system: TradingSystem):
    dash = HttpDashboard(system, port=18182)
    await dash.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", 18182)
    writer.write(b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = (await reader.read(4096)).decode("utf-8", errors="replace")
    writer.close()

    assert "200 OK" in response
    assert "market_intel" in response
    assert "strategy_gen" in response
    await dash.stop()


@pytest.mark.asyncio
async def test_dashboard_metrics_endpoint(system: TradingSystem):
    dash = HttpDashboard(system, port=18183)
    await dash.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", 18183)
    writer.write(b"GET /api/metrics HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = (await reader.read(4096)).decode("utf-8", errors="replace")
    writer.close()

    assert "200 OK" in response
    assert "trading_events" in response
    await dash.stop()


@pytest.mark.asyncio
async def test_dashboard_returns_html(system: TradingSystem):
    dash = HttpDashboard(system, port=18184)
    await dash.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", 18184)
    writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = (await reader.read(8192)).decode("utf-8", errors="replace")
    writer.close()

    assert "200 OK" in response
    assert "Trading Dashboard" in response
    assert "text/html" in response
    await dash.stop()


@pytest.mark.asyncio
async def test_dashboard_metrics_json_endpoint(system: TradingSystem):
    dash = HttpDashboard(system, port=18185)
    await dash.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", 18185)
    writer.write(b"GET /api/metrics/json HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = (await reader.read(4096)).decode("utf-8", errors="replace")
    writer.close()

    assert "200 OK" in response
    assert "total_events" in response
    assert "uptime_seconds" in response
    await dash.stop()


@pytest.mark.asyncio
async def test_dashboard_404(system: TradingSystem):
    dash = HttpDashboard(system, port=18186)
    await dash.start()

    reader, writer = await asyncio.open_connection("127.0.0.1", 18186)
    writer.write(b"GET /nonexistent HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = (await reader.read(4096)).decode("utf-8", errors="replace")
    writer.close()

    assert "404 Not Found" in response
    await dash.stop()


@pytest.mark.asyncio
async def test_dashboard_html_content(system: TradingSystem):
    assert "Trading Dashboard" in HTML
    assert "/api/health" in HTML
    assert "/api/metrics" in HTML
    assert "setInterval" in HTML
