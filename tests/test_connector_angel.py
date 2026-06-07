import pytest

from src.connectors.angel.client import AngelClient, AngelClientError


@pytest.fixture
def angel_client():
    return AngelClient()


@pytest.mark.asyncio
async def test_angel_client_init():
    client = AngelClient(api_key="", client_id="", password="", totp="")
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_angel_client_connect_no_key():
    client = AngelClient(api_key="", client_id="", password="", totp="")
    await client.connect()
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_angel_client_search_no_data(angel_client: AngelClient):
    results = await angel_client.search_instruments("RELIANCE")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_angel_client_get_ltp_no_key():
    import pytest

    from src.connectors.angel.client import AngelClientError

    client = AngelClient(api_key="", client_id="", password="", totp="")
    with pytest.raises((AngelClientError, Exception)):
        await client.get_ltp(["NSE:RELIANCE"])


@pytest.mark.asyncio
async def test_angel_client_handle_response_success():
    class FakeResp:
        status_code = 200

        def json(self):
            return {"status": True, "data": {"jwtToken": "abc"}}

    result = AngelClient._handle_response(FakeResp())
    assert result["jwtToken"] == "abc"


@pytest.mark.asyncio
async def test_angel_client_handle_response_error():
    class FakeResp:
        status_code = 400

        def json(self):
            return {"status": False, "message": "Invalid credentials"}

    with pytest.raises(AngelClientError, match="Invalid credentials"):
        AngelClient._handle_response(FakeResp())


@pytest.mark.asyncio
async def test_angel_historical_intervals():
    from src.connectors.angel.client import HISTORICAL_INTERVALS

    assert HISTORICAL_INTERVALS["minute"] == "ONE_MINUTE"
    assert HISTORICAL_INTERVALS["day"] == "ONE_DAY"
    assert HISTORICAL_INTERVALS["hour"] == "ONE_HOUR"
