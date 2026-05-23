import pytest

from src.connectors.yahoo import EXCHANGE_MAP, get_ltp_yahoo


def test_exchange_map():
    assert EXCHANGE_MAP["NSE"] == ".NS"
    assert EXCHANGE_MAP["BSE"] == ".BO"


@pytest.mark.asyncio
async def test_yahoo_ltp_real_symbol():
    result = await get_ltp_yahoo(["NSE:RELIANCE"])
    assert "NSE:RELIANCE" in result
    data = result["NSE:RELIANCE"]
    assert "last_price" in data
    assert data["last_price"] > 0
    assert "previous_close" in data
    assert data["previous_close"] > 0


@pytest.mark.asyncio
async def test_yahoo_ltp_multiple_symbols():
    result = await get_ltp_yahoo(["NSE:RELIANCE", "NSE:TCS"])
    assert "NSE:RELIANCE" in result or "NSE:TCS" in result


@pytest.mark.asyncio
async def test_yahoo_ltp_bad_symbol():
    result = await get_ltp_yahoo(["NSE:NONEXISTENT123XYZ"])
    assert result == {}
