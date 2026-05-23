from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from src.config.settings import settings

logger = logging.getLogger("connector.groww.client")


class GrowwAPIError(RuntimeError):
    pass


@dataclass
class GrowwClient:
    api_key: str = ""
    api_secret: str = ""
    totp_secret: str = ""
    auth_token: str = ""
    base_url: str = "https://api.groww.in/v1"
    timeout_seconds: int = 15

    def __post_init__(self):
        self.api_key = self.api_key or settings.groww_api_key
        self.api_secret = self.api_secret or settings.groww_api_secret
        self.totp_secret = self.totp_secret or settings.groww_totp_secret
        self.auth_token = self.auth_token or settings.groww_auth_token
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._build_headers(),
                timeout=self.timeout_seconds,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _build_headers(api_key: str | None = None) -> dict:
        return {
            "x-request-id": str(uuid.uuid4()),
            "Authorization": f"Bearer {api_key}" if api_key else "",
            "Content-Type": "application/json",
            "x-client-id": "growwapi",
            "x-client-platform": "growwapi-python-client",
            "x-client-platform-version": "1.5.0",
            "x-api-version": "1.0",
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        payload: dict | None = None,
        retry_on_401: bool = True,
    ) -> dict:
        client = await self._get_client()
        url = f"{self.base_url}{path}"
        try:
            response = await client.request(
                method=method.upper(),
                url=url,
                params=params,
                json=payload,
            )
            if response.status_code == 401 and retry_on_401:
                logger.warning("Groww API 401 Unauthorized — attempting token refresh")
                refreshed = await self._refresh_token()
                if refreshed:
                    client.headers.update(self._build_headers(self.api_key))
                    return await self._request(method, path, params, payload, retry_on_401=False)
                raise GrowwAPIError("Groww API 401 and token refresh failed")
            if not response.is_success:
                raise GrowwAPIError(
                    f"Groww API error on {path} ({response.status_code}): {response.text[:400]}"
                )
            return response.json()
        except httpx.TimeoutException as exc:
            raise GrowwAPIError(f"Timeout reaching Groww API at {path}: {exc}") from exc
        except httpx.RequestError as exc:
            raise GrowwAPIError(f"Failed to reach Groww API at {path}: {exc}") from exc

    async def _refresh_token(self) -> bool:
        import pyotp
        if not self.auth_token or not self.totp_secret:
            logger.error("Cannot refresh Groww token: missing auth_token or totp_secret")
            return False
        try:
            totp = pyotp.TOTP(self.totp_secret)
            otp = totp.now()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groww.in/token/api/access",
                    headers={
                        "Authorization": f"Bearer {self.auth_token}",
                        "Content-Type": "application/json",
                    },
                    json={"totp": otp},
                )
                if not resp.is_success:
                    logger.error("Groww token refresh failed: %s", resp.text[:200])
                    return False
                data = resp.json()
                new_token = data.get("access_token", "")
                if not new_token:
                    logger.error("Groww refresh response missing access_token")
                    return False
                self.api_key = new_token
                settings.groww_api_key = new_token
                logger.info("Groww token refreshed, valid until exp=%s", data.get("exp", "unknown"))
                return True
        except Exception as e:
            logger.error("Groww token refresh error: %s", e)
            return False

    async def get_live_quote(self, trading_symbol: str, exchange: str = "NSE", segment: str = "CASH") -> dict:
        return await self._request(
            "GET",
            "/live-data/quote",
            params={"exchange": exchange, "segment": segment, "trading_symbol": trading_symbol},
        )

    async def get_ltp(self, trading_symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> dict:
        exchange_symbols = ",".join(f"{exchange}_{s}" for s in trading_symbols)
        return await self._request(
            "GET", "/live-data/ltp", params={"segment": segment, "exchange_symbols": exchange_symbols}
        )

    async def get_ohlc(self, trading_symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> dict:
        exchange_symbols = ",".join(f"{exchange}_{s}" for s in trading_symbols)
        return await self._request(
            "GET", "/live-data/ohlc", params={"segment": segment, "exchange_symbols": exchange_symbols}
        )

    async def get_historical_candles(
        self,
        trading_symbol: str,
        start_time: str,
        end_time: str,
        exchange: str = "NSE",
        segment: str = "CASH",
        interval_in_minutes: str | None = None,
    ) -> dict:
        params = {
            "exchange": exchange,
            "segment": segment,
            "trading_symbol": trading_symbol,
            "start_time": start_time,
            "end_time": end_time,
        }
        if interval_in_minutes is not None:
            params["interval_in_minutes"] = interval_in_minutes
        return await self._request("GET", "/historical/candle/range", params=params)
