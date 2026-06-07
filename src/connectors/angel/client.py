import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from src.connectors.angel.symbol_index import AngelSymbolIndex

logger = logging.getLogger("connector.angel.client")

BASE_URL = "https://apiconnect.angelbroking.com"
HISTORICAL_INTERVALS = {
    "minute": "ONE_MINUTE",
    "3minute": "THREE_MINUTE",
    "5minute": "FIVE_MINUTE",
    "10minute": "TEN_MINUTE",
    "15minute": "FIFTEEN_MINUTE",
    "30minute": "THIRTY_MINUTE",
    "hour": "ONE_HOUR",
    "day": "ONE_DAY",
}


class AngelClientError(Exception):
    pass


class AngelClient:
    def __init__(
        self,
        api_key: str | None = None,
        client_id: str | None = None,
        password: str | None = None,
        totp: str | None = None,
        symbol_index: AngelSymbolIndex | None = None,
    ):
        from src.config.settings import settings as _s

        self._api_key = api_key if api_key is not None else _s.angel_api_key
        self._client_id = client_id if client_id is not None else _s.angel_client_id
        self._password = password if password is not None else _s.angel_password
        self._totp = totp if totp is not None else _s.angel_totp
        self._jwt_token: str | None = None
        self._refresh_token: str | None = None
        self._feed_token: str | None = None
        self._token_expiry: datetime | None = None
        self._http = httpx.AsyncClient(timeout=15.0)
        self._symbol_map: dict[str, dict[str, Any]] = {}
        self._symbol_index = symbol_index or AngelSymbolIndex(
            fetch_symbols=self._fetch_symbol_master,
        )
        self._lock = asyncio.Lock()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        from src.utils.retry import with_retry

        async def make_call():
            return await self._http.request(method, url, **kwargs)

        return await with_retry(
            make_call,
            exceptions=(httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError),
        )

    @property
    def is_connected(self) -> bool:
        return self._jwt_token is not None

    @property
    def api_key(self) -> str:
        return self._api_key or ""

    @property
    def client_id(self) -> str:
        return self._client_id or ""

    @property
    def jwt_token(self) -> str | None:
        return self._jwt_token

    @property
    def feed_token(self) -> str | None:
        return self._feed_token

    async def connect(self) -> None:
        if self.is_connected:
            return
        if not self._api_key:
            logger.warning("Angel API key not set — running in paper mode")
            return
        await self._login()

    async def _login(self) -> None:
        totp_code = self._totp
        if self._totp and len(self._totp) > 6:
            try:
                import pyotp

                totp_code = pyotp.TOTP(self._totp).now()
                logger.debug("Auto-generated TOTP code")
            except Exception:
                pass
        body = {
            "clientcode": self._client_id,
            "password": self._password,
            "totp": totp_code,
        }
        resp = await self._request(
            "POST",
            f"{BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
            json=body,
            headers=self._default_headers(auth=False),
        )
        data = self._handle_response(resp)
        self._jwt_token = data["jwtToken"]
        self._refresh_token = data.get("refreshToken")
        self._feed_token = data.get("feedToken")
        self._token_expiry = datetime.now(UTC) + timedelta(hours=1)
        logger.info("Angel One SmartAPI login successful")

    async def _ensure_token(self) -> None:
        if not self._jwt_token:
            if self._api_key:
                await self._login()
            return
        if self._token_expiry and datetime.now(UTC) >= self._token_expiry:
            if self._refresh_token:
                await self._refresh_login()
            else:
                await self._login()

    async def ensure_token(self) -> None:
        await self._ensure_token()

    async def _refresh_login(self) -> None:
        body = {
            "clientcode": self._client_id,
            "refreshtoken": self._refresh_token,
        }
        resp = await self._request(
            "POST",
            f"{BASE_URL}/rest/auth/angelbroking/user/v1/refreshToken",
            json=body,
            headers=self._default_headers(auth=False),
        )
        data = self._handle_response(resp)
        self._jwt_token = data["jwtToken"]
        self._token_expiry = datetime.now(UTC) + timedelta(hours=1)
        logger.info("Angel token refreshed")

    async def search_instruments(self, query: str) -> list[dict[str, Any]]:
        return await self._symbol_index.search(query)

    async def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        await self._ensure_token()
        results = {}
        for instr in instruments:
            parts = instr.split(":")
            exchange = parts[0] if len(parts) > 1 else "NSE"
            symbol = parts[1] if len(parts) > 1 else instr
            token = await self._resolve_token(symbol, exchange)
            if not token:
                continue
            body = {"exchange": exchange, "tradingsymbol": symbol, "symboltoken": token}
            resp = await self._request(
                "POST",
                f"{BASE_URL}/rest/secure/angelbroking/quote/v1/ltp",
                json=body,
                headers=self._auth_headers(),
            )
            data = self._handle_response(resp)
            if data.get("data"):
                results[instr] = {
                    "last_price": float(data["data"].get("ltp", 0)),
                    "volume": data["data"].get("volume"),
                }
        return results

    async def get_quote(self, instrument: str, exchange: str = "NSE") -> dict[str, Any]:
        await self._ensure_token()
        token = await self._resolve_token(instrument, exchange)
        if not token:
            return {}
        body = {"exchange": exchange, "tradingsymbol": instrument, "symboltoken": token}
        resp = await self._request(
            "POST",
            f"{BASE_URL}/rest/secure/angelbroking/quote/v1/ltp",
            json=body,
            headers=self._auth_headers(),
        )
        data = self._handle_response(resp)
        return data.get("data", {})

    async def get_historical_data(
        self,
        instrument: str,
        interval: str = "day",
        from_date: str | None = None,
        to_date: str | None = None,
        exchange: str = "NSE",
    ) -> list[dict[str, Any]]:
        await self._ensure_token()
        angel_interval = HISTORICAL_INTERVALS.get(interval, "ONE_DAY")
        token = await self._resolve_token(instrument, exchange)
        if not token:
            raise AngelClientError(f"Symbol token not found for {instrument} on {exchange}")

        to_date = to_date or datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        from_date = from_date or (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")

        body = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": angel_interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        resp = await self._request(
            "POST",
            f"{BASE_URL}/rest/secure/angelbroking/historical/v1/getCandleData",
            json=body,
            headers=self._auth_headers(),
        )
        data = self._handle_response(resp)
        raw = data.get("data", [])
        candles = []
        for item in raw:
            if isinstance(item, list) and len(item) >= 6:
                candles.append(
                    {
                        "timestamp": item[0],
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": int(item[5]),
                    }
                )
        return candles

    async def _resolve_token(self, tradingsymbol: str, exchange: str) -> str | None:
        return await self._symbol_index.resolve_token(tradingsymbol, exchange)

    async def resolve_token(self, tradingsymbol: str, exchange: str) -> str | None:
        return await self._resolve_token(tradingsymbol, exchange)

    async def _load_symbol_map(self) -> None:
        self._symbol_map = await self._symbol_index.load()

    async def _fetch_symbol_master(self) -> list[dict[str, Any]]:
        if not self._api_key:
            return []
        try:
            resp = await self._request(
                "GET",
                "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
                timeout=30.0,
            )
            resp.raise_for_status()
            symbols = resp.json()
            logger.info("Loaded %d symbols from Angel master contract", len(symbols))
            return symbols
        except Exception as e:
            logger.error("Failed to load Angel symbol map: %s", e)
            raise

    async def disconnect(self) -> None:
        await self._http.aclose()
        self._jwt_token = None
        self._feed_token = None

    def _default_headers(self, auth: bool = True) -> dict[str, str]:
        public_ip = self._resolve_public_ip()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": public_ip,
            "X-ClientPublicIP": public_ip,
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self._api_key,
        }
        if auth and self._jwt_token:
            headers["Authorization"] = f"Bearer {self._jwt_token}"
        return headers

    def _auth_headers(self) -> dict[str, str]:
        return self._default_headers(auth=True)

    _public_ip: str | None = None

    def _resolve_public_ip(self) -> str:
        if AngelClient._public_ip:
            return AngelClient._public_ip
        try:
            import httpx

            resp = httpx.get("https://ifconfig.me/ip", timeout=5)
            AngelClient._public_ip = resp.text.strip()
        except Exception:
            AngelClient._public_ip = "127.0.0.1"
        return AngelClient._public_ip

    @staticmethod
    def _handle_response(resp: httpx.Response) -> Any:
        try:
            data = resp.json()
        except Exception:
            raise AngelClientError(f"Invalid response: {resp.status_code} {resp.text[:500]}")

        if resp.status_code != 200 or not data.get("status"):
            error_msg = data.get("message", data.get("error", f"HTTP {resp.status_code}"))
            raise AngelClientError(error_msg)

        raw = data.get("data", data)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            return {"data": raw}
        return raw
