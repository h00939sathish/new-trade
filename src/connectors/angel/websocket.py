import asyncio
import inspect
import json
import logging
import ssl
import struct
import threading
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Protocol

logger = logging.getLogger("connector.angel.websocket")


class AngelWebSocketMode(IntEnum):
    LTP = 1
    QUOTE = 2
    SNAP_QUOTE = 3
    DEPTH = 4


EXCHANGE_TYPE_BY_NAME = {
    "NSE": 1,
    "NSE_CM": 1,
    "NFO": 2,
    "NSE_FO": 2,
    "BSE": 3,
    "BSE_CM": 3,
    "BFO": 4,
    "BSE_FO": 4,
    "MCX": 5,
    "MCX_FO": 5,
    "NCX": 7,
    "NCX_FO": 7,
    "CDS": 13,
    "CDE": 13,
    "CDE_FO": 13,
}
EXCHANGE_NAME_BY_TYPE = {
    1: "NSE",
    2: "NFO",
    3: "BSE",
    4: "BFO",
    5: "MCX",
    7: "NCX",
    13: "CDS",
}


class AngelWebSocketError(Exception):
    pass


@dataclass(frozen=True)
class AngelWebSocketSubscription:
    exchange: str
    symbol_token: str
    tradingsymbol: str | None = None

    @property
    def exchange_type(self) -> int:
        exchange_type = EXCHANGE_TYPE_BY_NAME.get(self.exchange.upper())
        if exchange_type is None:
            raise AngelWebSocketError(f"Unsupported Angel exchange: {self.exchange}")
        return exchange_type


class WebSocketSession(Protocol):
    async def connect(self) -> None:
        pass

    async def send(self, payload: str) -> None:
        pass

    async def close(self) -> None:
        pass


SessionFactory = Callable[
    [str, dict[str, str], Callable[[Any], Awaitable[None]]],
    WebSocketSession,
]
TickCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
DisconnectCallback = Callable[[str], Awaitable[None] | None]


class WebSocketAppSession:
    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        on_message: Callable[[Any], Awaitable[None]],
        on_disconnect: DisconnectCallback | None = None,
        open_timeout: float = 5.0,
    ) -> None:
        self._url = url
        self._headers = headers
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._open_timeout = open_timeout
        self._app: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._open_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._disconnect_notified = False

    async def connect(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise AngelWebSocketError(
                "Install websocket-client to use Angel live WebSocket streaming"
            ) from exc

        self._loop = asyncio.get_running_loop()

        def on_open(_wsapp: Any) -> None:
            self._open_event.set()

        def on_message(_wsapp: Any, message: Any) -> None:
            self._dispatch_message(message)

        def on_data(_wsapp: Any, data: Any, _data_type: int, _continue_flag: bool) -> None:
            self._dispatch_message(data)

        def on_error(_wsapp: Any, error: Any) -> None:
            logger.error("Angel WebSocket error: %s", error)
            self._dispatch_disconnect(str(error))

        def on_close(_wsapp: Any, _code: Any, message: Any) -> None:
            reason = message if isinstance(message, str) and message else "closed"
            self._dispatch_disconnect(reason)

        self._app = websocket.WebSocketApp(
            self._url,
            header=_header_lines(self._headers),
            on_open=on_open,
            on_message=on_message,
            on_data=on_data,
            on_error=on_error,
            on_close=on_close,
        )
        self._thread = threading.Thread(
            target=lambda: self._app.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=10,
            ),
            name="angel-smartapi-websocket",
            daemon=True,
        )
        self._thread.start()
        opened = await asyncio.to_thread(self._open_event.wait, self._open_timeout)
        if not opened:
            raise AngelWebSocketError("Timed out opening Angel WebSocket")

    async def send(self, payload: str) -> None:
        if not self._app:
            raise AngelWebSocketError("Angel WebSocket is not connected")
        await asyncio.to_thread(self._app.send, payload)

    async def close(self) -> None:
        if self._app:
            await asyncio.to_thread(self._app.close)
        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 1.0)

    def _dispatch_message(self, message: Any) -> None:
        if not self._loop:
            return
        self._loop.call_soon_threadsafe(asyncio.create_task, self._on_message(message))

    def _dispatch_disconnect(self, reason: str) -> None:
        if not self._loop or not self._on_disconnect or self._disconnect_notified:
            return
        self._disconnect_notified = True
        self._loop.call_soon_threadsafe(asyncio.create_task, self._on_disconnect(reason))


class AngelWebSocketClient:
    ROOT_URI = "wss://smartapisocket.angelone.in/smart-stream"
    SUBSCRIBE_ACTION = 1
    UNSUBSCRIBE_ACTION = 0

    def __init__(
        self,
        api_key: str,
        client_code: str,
        auth_token: str,
        feed_token: str,
        on_tick: TickCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        if not all([api_key, client_code, auth_token, feed_token]):
            raise AngelWebSocketError(
                "Angel WebSocket requires api key, client code, auth token, and feed token"
            )
        self._api_key = api_key
        self._client_code = client_code
        self._auth_token = auth_token
        self._feed_token = feed_token
        self._on_tick = on_tick
        self._on_disconnect = on_disconnect
        self._session_factory = session_factory or WebSocketAppSession
        self._session: WebSocketSession | None = None
        self._subscriptions: dict[tuple[int, int, str], AngelWebSocketSubscription] = {}

    async def connect(self) -> None:
        if self._session:
            return
        self._session = self._session_factory(
            self.ROOT_URI,
            {
                "Authorization": self._auth_token,
                "x-api-key": self._api_key,
                "x-client-code": self._client_code,
                "x-feed-token": self._feed_token,
            },
            self.handle_message,
            self._on_disconnect,
        )
        await self._session.connect()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def subscribe(
        self,
        subscriptions: Iterable[AngelWebSocketSubscription],
        mode: AngelWebSocketMode = AngelWebSocketMode.LTP,
        correlation_id: str = "stream0001",
    ) -> None:
        await self._send_subscription_action(
            action=self.SUBSCRIBE_ACTION,
            subscriptions=list(subscriptions),
            mode=mode,
            correlation_id=correlation_id,
        )

    async def unsubscribe(
        self,
        subscriptions: Iterable[AngelWebSocketSubscription],
        mode: AngelWebSocketMode = AngelWebSocketMode.LTP,
        correlation_id: str = "stream0001",
    ) -> None:
        await self._send_subscription_action(
            action=self.UNSUBSCRIBE_ACTION,
            subscriptions=list(subscriptions),
            mode=mode,
            correlation_id=correlation_id,
        )

    def register_subscription(
        self,
        subscription: AngelWebSocketSubscription,
        mode: AngelWebSocketMode = AngelWebSocketMode.LTP,
    ) -> None:
        key = (int(mode), subscription.exchange_type, subscription.symbol_token)
        self._subscriptions[key] = subscription

    async def handle_message(self, message: Any) -> None:
        parsed = self._parse_message(message)
        if not parsed:
            return
        normalized = self._normalize_tick(parsed)
        if normalized and self._on_tick:
            result = self._on_tick(normalized)
            if inspect.isawaitable(result):
                await result

    async def _send_subscription_action(
        self,
        action: int,
        subscriptions: list[AngelWebSocketSubscription],
        mode: AngelWebSocketMode,
        correlation_id: str,
    ) -> None:
        if not self._session:
            raise AngelWebSocketError("Angel WebSocket is not connected")
        if mode == AngelWebSocketMode.DEPTH:
            bad_exchange = [sub.exchange for sub in subscriptions if sub.exchange_type != 1]
            if bad_exchange:
                raise AngelWebSocketError("Angel depth mode supports NSE cash instruments only")

        token_list = self._build_token_list(subscriptions)
        request = {
            "correlationID": correlation_id,
            "action": action,
            "params": {
                "mode": int(mode),
                "tokenList": token_list,
            },
        }
        if action == self.SUBSCRIBE_ACTION:
            for subscription in subscriptions:
                self.register_subscription(subscription, mode)
        else:
            for subscription in subscriptions:
                self._subscriptions.pop(
                    (int(mode), subscription.exchange_type, subscription.symbol_token),
                    None,
                )
        await self._session.send(json.dumps(request))

    @staticmethod
    def _build_token_list(
        subscriptions: Iterable[AngelWebSocketSubscription],
    ) -> list[dict[str, Any]]:
        grouped: dict[int, list[str]] = defaultdict(list)
        for subscription in subscriptions:
            token = str(subscription.symbol_token)
            if token not in grouped[subscription.exchange_type]:
                grouped[subscription.exchange_type].append(token)
        return [
            {"exchangeType": exchange_type, "tokens": tokens}
            for exchange_type, tokens in grouped.items()
        ]

    def _normalize_tick(self, parsed: dict[str, Any]) -> dict[str, Any] | None:
        token = str(parsed.get("token") or parsed.get("symbolToken") or "")
        if not token:
            return None
        mode = int(parsed.get("subscription_mode") or AngelWebSocketMode.LTP)
        exchange_type = int(parsed.get("exchange_type") or parsed.get("exchangeType") or 0)
        subscription = self._subscriptions.get((mode, exchange_type, token))
        exchange = (
            subscription.exchange
            if subscription
            else EXCHANGE_NAME_BY_TYPE.get(exchange_type, str(exchange_type))
        )
        instrument = subscription.tradingsymbol if subscription else token
        raw_price = parsed.get("last_traded_price", parsed.get("ltp"))
        volume = parsed.get("volume_trade_for_the_day", parsed.get("volume"))
        return {
            "instrument": instrument or token,
            "exchange": exchange,
            "token": token,
            "last_price": _price_from_paise(raw_price),
            "volume": volume,
            "exchange_timestamp": parsed.get("exchange_timestamp"),
            "raw": parsed,
        }

    @staticmethod
    def _parse_message(message: Any) -> dict[str, Any] | None:
        if message in (None, "pong"):
            return None
        if isinstance(message, dict):
            return message
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        if isinstance(message, bytes | bytearray):
            return _parse_binary_tick(bytes(message))
        return None


def _price_from_paise(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int):
        return value / 100
    return float(value)


def _parse_binary_tick(packet: bytes) -> dict[str, Any] | None:
    if len(packet) < 51:
        return None
    parsed: dict[str, Any] = {
        "subscription_mode": struct.unpack_from("<B", packet, 0)[0],
        "exchange_type": struct.unpack_from("<B", packet, 1)[0],
        "token": packet[2:27].split(b"\x00", 1)[0].decode("ascii", errors="ignore"),
        "sequence_number": struct.unpack_from("<q", packet, 27)[0],
        "exchange_timestamp": struct.unpack_from("<q", packet, 35)[0],
        "last_traded_price": struct.unpack_from("<q", packet, 43)[0],
    }
    if len(packet) >= 75:
        parsed["last_traded_quantity"] = struct.unpack_from("<q", packet, 51)[0]
        parsed["average_traded_price"] = struct.unpack_from("<q", packet, 59)[0]
        parsed["volume_trade_for_the_day"] = struct.unpack_from("<q", packet, 67)[0]
    return parsed


def _header_lines(headers: dict[str, str]) -> list[str]:
    return [f"{key}: {value}" for key, value in headers.items()]
