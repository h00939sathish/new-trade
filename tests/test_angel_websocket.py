import asyncio
import json

import pytest

from src.connectors.angel.market_data import AngelMarketDataProvider
from src.connectors.angel.websocket import (
    AngelWebSocketClient,
    AngelWebSocketMode,
    AngelWebSocketSubscription,
    _header_lines,
)


class FakeSocketSession:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.sent: list[dict] = []

    async def connect(self) -> None:
        self.connected = True

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_websocket_connects_with_angel_headers():
    session = FakeSocketSession()
    captured = {}

    def session_factory(url, headers, on_message, on_disconnect=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["on_message"] = on_message
        captured["on_disconnect"] = on_disconnect
        return session

    client = AngelWebSocketClient(
        api_key="api-key",
        client_code="client-code",
        auth_token="jwt-token",
        feed_token="feed-token",
        session_factory=session_factory,
    )

    await client.connect()

    assert session.connected is True
    assert captured["url"] == "wss://smartapisocket.angelone.in/smart-stream"
    assert captured["headers"] == {
        "Authorization": "jwt-token",
        "x-api-key": "api-key",
        "x-client-code": "client-code",
        "x-feed-token": "feed-token",
    }


@pytest.mark.asyncio
async def test_websocket_subscribe_groups_tokens_by_exchange():
    session = FakeSocketSession()
    client = AngelWebSocketClient(
        api_key="api-key",
        client_code="client-code",
        auth_token="jwt-token",
        feed_token="feed-token",
        session_factory=lambda *_args: session,
    )
    await client.connect()

    await client.subscribe(
        [
            AngelWebSocketSubscription(exchange="NSE", symbol_token="2885"),
            AngelWebSocketSubscription(exchange="NSE", symbol_token="3045"),
            AngelWebSocketSubscription(exchange="NFO", symbol_token="35000"),
        ],
        mode=AngelWebSocketMode.LTP,
        correlation_id="test000001",
    )

    assert session.sent == [
        {
            "correlationID": "test000001",
            "action": 1,
            "params": {
                "mode": 1,
                "tokenList": [
                    {"exchangeType": 1, "tokens": ["2885", "3045"]},
                    {"exchangeType": 2, "tokens": ["35000"]},
                ],
            },
        },
    ]


@pytest.mark.asyncio
async def test_websocket_unsubscribe_uses_action_zero():
    session = FakeSocketSession()
    client = AngelWebSocketClient(
        api_key="api-key",
        client_code="client-code",
        auth_token="jwt-token",
        feed_token="feed-token",
        session_factory=lambda *_args: session,
    )
    await client.connect()

    await client.unsubscribe(
        [AngelWebSocketSubscription(exchange="BSE", symbol_token="500325")],
        mode=AngelWebSocketMode.QUOTE,
        correlation_id="test000002",
    )

    assert session.sent[0]["action"] == 0
    assert session.sent[0]["params"]["mode"] == 2
    assert session.sent[0]["params"]["tokenList"] == [
        {"exchangeType": 3, "tokens": ["500325"]},
    ]


@pytest.mark.asyncio
async def test_websocket_normalizes_ltp_tick_from_parsed_sdk_message():
    ticks = []

    async def on_tick(tick):
        ticks.append(tick)

    client = AngelWebSocketClient(
        api_key="api-key",
        client_code="client-code",
        auth_token="jwt-token",
        feed_token="feed-token",
        on_tick=on_tick,
    )
    client.register_subscription(
        AngelWebSocketSubscription(
            exchange="NSE",
            symbol_token="2885",
            tradingsymbol="RELIANCE-EQ",
        ),
        mode=AngelWebSocketMode.LTP,
    )

    await client.handle_message(
        {
            "subscription_mode": 1,
            "exchange_type": 1,
            "token": "2885",
            "sequence_number": 42,
            "exchange_timestamp": 1716537600000,
            "last_traded_price": 248025,
            "volume_trade_for_the_day": 1200,
        }
    )

    assert ticks == [
        {
            "instrument": "RELIANCE-EQ",
            "exchange": "NSE",
            "token": "2885",
            "last_price": 2480.25,
            "volume": 1200,
            "exchange_timestamp": 1716537600000,
            "raw": {
                "subscription_mode": 1,
                "exchange_type": 1,
                "token": "2885",
                "sequence_number": 42,
                "exchange_timestamp": 1716537600000,
                "last_traded_price": 248025,
                "volume_trade_for_the_day": 1200,
            },
        },
    ]


@pytest.mark.asyncio
async def test_market_data_provider_prefers_websocket_when_tokens_are_available():
    ticks = []
    session = FakeSocketSession()

    class FakeAngelClient:
        api_key = "api-key"
        client_id = "client-code"
        jwt_token = "jwt-token"
        feed_token = "feed-token"

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def ensure_token(self) -> None:
            return None

        async def resolve_token(self, tradingsymbol: str, exchange: str) -> str | None:
            assert (tradingsymbol, exchange) == ("RELIANCE-EQ", "NSE")
            return "2885"

    provider = AngelMarketDataProvider(
        client=FakeAngelClient(),
        on_tick=lambda tick: ticks.append(tick),
        websocket_factory=lambda **kwargs: AngelWebSocketClient(
            **kwargs,
            session_factory=lambda *_args: session,
        ),
    )
    provider.add_instrument("RELIANCE-EQ", "NSE")

    await provider.start()

    assert session.connected is True
    assert session.sent[0]["action"] == 1
    assert session.sent[0]["params"]["tokenList"] == [
        {"exchangeType": 1, "tokens": ["2885"]},
    ]

    await provider.stop()
    assert session.closed is True


@pytest.mark.asyncio
async def test_market_data_provider_uses_supplied_symbol_token_without_master_lookup():
    session = FakeSocketSession()

    class FakeAngelClient:
        api_key = "api-key"
        client_id = "client-code"
        jwt_token = "jwt-token"
        feed_token = "feed-token"

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def ensure_token(self) -> None:
            return None

        async def resolve_token(self, tradingsymbol: str, exchange: str) -> str | None:
            raise AssertionError("symbol master lookup should not be used")

    provider = AngelMarketDataProvider(
        client=FakeAngelClient(),
        websocket_factory=lambda **kwargs: AngelWebSocketClient(
            **kwargs,
            session_factory=lambda *_args: session,
        ),
    )
    provider.add_instrument("RELIANCE-EQ", "NSE", symbol_token="2885")

    await provider.start()

    assert session.sent[0]["params"]["tokenList"] == [
        {"exchangeType": 1, "tokens": ["2885"]},
    ]

    await provider.stop()


@pytest.mark.asyncio
async def test_market_data_provider_falls_back_to_polling_after_websocket_disconnect():
    session = FakeSocketSession()
    captured = {}
    polling_started = asyncio.Event()

    class FakeAngelClient:
        api_key = "api-key"
        client_id = "client-code"
        jwt_token = "jwt-token"
        feed_token = "feed-token"

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def ensure_token(self) -> None:
            return None

        async def resolve_token(self, tradingsymbol: str, exchange: str) -> str | None:
            return "2885"

    provider = AngelMarketDataProvider(
        client=FakeAngelClient(),
        websocket_factory=lambda **kwargs: AngelWebSocketClient(
            **kwargs,
            session_factory=lambda _url, _headers, _on_message, on_disconnect=None: (
                _capture_session(
                    captured,
                    session,
                    on_disconnect,
                )
            ),
        ),
    )

    async def fake_poll_loop() -> None:
        polling_started.set()
        await asyncio.sleep(3600)

    provider._poll_loop = fake_poll_loop
    provider.add_instrument("RELIANCE-EQ", "NSE")

    await provider.start()
    await captured["on_disconnect"]("Connection to remote host was lost.")
    await asyncio.wait_for(polling_started.wait(), timeout=1.0)

    assert provider._websocket is None

    await provider.stop()


def test_websocket_app_headers_are_serialized_as_header_lines():
    assert _header_lines(
        {
            "Authorization": "jwt-token",
            "x-api-key": "api-key",
        }
    ) == [
        "Authorization: jwt-token",
        "x-api-key: api-key",
    ]


def _capture_session(captured, session, on_disconnect):
    captured["on_disconnect"] = on_disconnect
    return session
