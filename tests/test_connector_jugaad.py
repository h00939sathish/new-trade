import pytest

from src.connectors.jugaad.client import JugaadClient


@pytest.fixture
def client():
    return JugaadClient()


@pytest.mark.asyncio
async def test_client_connect(client: JugaadClient):
    assert client.is_connected is False
    await client.connect()
    assert client.is_connected is True
    await client.disconnect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_search_symbols(client: JugaadClient):
    await client.connect()
    results = await client.search_symbols("RELIANCE")
    assert len(results) >= 1
    assert results[0]["symbol"] == "RELIANCE"
    await client.disconnect()


@pytest.mark.asyncio
async def test_get_quote_returns_empty(client: JugaadClient):
    result = await client.get_quote("RELIANCE")
    assert result == {}


@pytest.mark.asyncio
async def test_get_ltp_returns_yahoo_data(client: JugaadClient):
    """get_ltp now proxies to Yahoo Finance and should return a dict
    (possibly with real data if network is available)."""
    result = await client.get_ltp(["NSE:RELIANCE"])
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_historical(client: JugaadClient):
    from datetime import date, timedelta

    await client.connect()
    today = date.today()
    candles = await client.get_historical(
        symbol="RELIANCE",
        from_date=today - timedelta(days=7),
        to_date=today,
    )
    assert isinstance(candles, list)
    if candles:
        c = candles[0]
        assert "open" in c
        assert "high" in c
        assert "low" in c
        assert "close" in c
        assert "volume" in c
    await client.disconnect()
