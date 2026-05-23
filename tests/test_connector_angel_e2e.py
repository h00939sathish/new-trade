import pytest

from src.connectors.angel.client import AngelClient, AngelClientError

pytestmark = pytest.mark.xfail(
    strict=False,
    reason="Angel One API rate limits (403) during testing; static IP propagation may still be pending",
)


@pytest.fixture
def angel_client():
    return AngelClient()


@pytest.mark.asyncio
async def test_angel_connect(angel_client: AngelClient):
    await angel_client.connect()
    assert angel_client.is_connected is True
    public_ip = angel_client._resolve_public_ip()
    assert public_ip != "127.0.0.1"
    assert "." in public_ip
    await angel_client.disconnect()


@pytest.mark.asyncio
async def test_angel_historical_data(angel_client: AngelClient):
    await angel_client.connect()
    candles = await angel_client.get_historical_data(
        instrument="RELIANCE",
        interval="day",
        from_date="2026-05-20 09:15",
        to_date="2026-05-23 15:30",
    )
    assert isinstance(candles, list)
    assert len(candles) >= 1
    c = candles[0]
    assert "open" in c
    assert "high" in c
    assert "low" in c
    assert "close" in c
    assert "volume" in c
    await angel_client.disconnect()


@pytest.mark.asyncio
async def test_angel_rejects_bad_symbol():
    client = AngelClient()
    await client.connect()
    with pytest.raises(AngelClientError):
        await client.get_historical_data(
            instrument="NONEXISTENT123",
            interval="day",
            from_date="2026-05-20 09:15",
            to_date="2026-05-23 15:30",
        )
    await client.disconnect()
