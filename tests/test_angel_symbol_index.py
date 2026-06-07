import json

import pytest

from src.connectors.angel.symbol_index import AngelSymbolIndex


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _symbols():
    return [
        {
            "token": "2885",
            "symbol": "RELIANCE-EQ",
            "name": "RELIANCE",
            "exch_seg": "NSE",
            "lotsize": "1",
            "tick_size": "5.000000",
            "instrumenttype": "",
            "expiry": "",
        },
    ]


@pytest.mark.asyncio
async def test_symbol_index_refreshes_and_persists_cache(tmp_path):
    calls = 0

    async def fetch_symbols():
        nonlocal calls
        calls += 1
        return _symbols()

    path = tmp_path / "angel_symbols.json"
    index = AngelSymbolIndex(path, fetch_symbols=fetch_symbols, clock=Clock())

    symbols = await index.load()

    assert symbols["2885"]["tradingsymbol"] == "RELIANCE-EQ"
    assert json.loads(path.read_text())["symbols"]["2885"]["exchange"] == "NSE"
    assert calls == 1


@pytest.mark.asyncio
async def test_symbol_index_loads_fresh_cache_without_network(tmp_path):
    path = tmp_path / "angel_symbols.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": 1_000.0,
                "symbols": {
                    "2885": {
                        "tradingsymbol": "RELIANCE-EQ",
                        "name": "RELIANCE",
                        "exchange": "NSE",
                    },
                },
            }
        )
    )

    async def fetch_symbols():
        raise AssertionError("fresh cache should avoid network")

    index = AngelSymbolIndex(path, fetch_symbols=fetch_symbols, clock=Clock())

    assert await index.resolve_token("RELIANCE-EQ", "NSE") == "2885"


@pytest.mark.asyncio
async def test_symbol_index_uses_stale_cache_when_refresh_fails(tmp_path):
    path = tmp_path / "angel_symbols.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": 1.0,
                "symbols": {
                    "2885": {
                        "tradingsymbol": "RELIANCE-EQ",
                        "name": "RELIANCE",
                        "exchange": "NSE",
                    },
                },
            }
        )
    )

    async def fetch_symbols():
        raise TimeoutError("Angel master contract unavailable")

    index = AngelSymbolIndex(path, fetch_symbols=fetch_symbols, clock=Clock())

    assert await index.resolve_token("RELIANCE", "NSE") == "2885"


@pytest.mark.asyncio
async def test_symbol_index_searches_cached_symbols(tmp_path):
    async def fetch_symbols():
        return _symbols()

    index = AngelSymbolIndex(tmp_path / "angel_symbols.json", fetch_symbols=fetch_symbols)

    assert await index.search("reli") == [
        {
            "instrument_token": "2885",
            "tradingsymbol": "RELIANCE-EQ",
            "name": "RELIANCE",
            "exchange": "NSE",
            "lot_size": 1,
            "tick_size": 5.0,
            "instrument_type": "",
            "expiry": "",
        },
    ]
