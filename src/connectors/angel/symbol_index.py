import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("connector.angel.symbol_index")

SymbolMap = dict[str, dict[str, Any]]
FetchSymbols = Callable[[], Awaitable[list[dict[str, Any]]]]


class AngelSymbolIndex:
    def __init__(
        self,
        cache_path: Path = Path("state/angel_symbols.json"),
        fetch_symbols: FetchSymbols | None = None,
        max_age_seconds: float = 24 * 60 * 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cache_path = cache_path
        self._fetch_symbols = fetch_symbols
        self._max_age_seconds = max_age_seconds
        self._clock = clock
        self._symbols: SymbolMap = {}

    async def load(self) -> SymbolMap:
        if self._symbols:
            return self._symbols

        cached_symbols, updated_at = self._read_cache()
        is_fresh = (
            cached_symbols
            and updated_at is not None
            and self._clock() - updated_at <= self._max_age_seconds
        )
        if is_fresh:
            self._symbols = cached_symbols
            return self._symbols

        if self._fetch_symbols is not None:
            try:
                raw_symbols = await self._fetch_symbols()
                self._symbols = self._normalize_symbols(raw_symbols)
                self._write_cache(self._symbols)
                return self._symbols
            except Exception as exc:
                logger.warning("Angel symbol refresh failed; using stale cache: %s", exc)

        self._symbols = cached_symbols
        return self._symbols

    async def resolve_token(self, tradingsymbol: str, exchange: str) -> str | None:
        symbols = await self.load()
        up_symbol = tradingsymbol.upper()
        up_exchange = exchange.upper()
        for token, meta in symbols.items():
            symbol = str(meta.get("tradingsymbol", "")).upper()
            name = str(meta.get("name", "")).upper()
            segment = str(meta.get("exchange", "")).upper()
            if segment == up_exchange and up_symbol in (symbol, name):
                return token
        return None

    async def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        symbols = await self.load()
        up_query = query.upper()
        results = []
        for token, meta in symbols.items():
            symbol = str(meta.get("tradingsymbol", "")).upper()
            name = str(meta.get("name", "")).upper()
            if up_query in symbol or up_query in name:
                results.append({"instrument_token": token, **meta})
            if len(results) >= limit:
                break
        return results

    def _read_cache(self) -> tuple[SymbolMap, float | None]:
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            symbols = payload.get("symbols", {})
            updated_at = payload.get("updated_at")
            if isinstance(symbols, dict):
                return symbols, float(updated_at) if updated_at is not None else None
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
        return {}, None

    def _write_cache(self, symbols: SymbolMap) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": self._clock(), "symbols": symbols}
        self._cache_path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _normalize_symbols(raw_symbols: list[dict[str, Any]]) -> SymbolMap:
        symbols = {}
        for entry in raw_symbols:
            token = str(entry.get("token", ""))
            if not token:
                continue
            symbols[token] = {
                "tradingsymbol": entry.get("symbol", ""),
                "name": entry.get("name", ""),
                "exchange": entry.get("exch_seg", ""),
                "lot_size": int(entry.get("lotsize", 1)),
                "tick_size": float(entry.get("tick_size", 0.05)),
                "instrument_type": entry.get("instrumenttype", ""),
                "expiry": entry.get("expiry", ""),
            }
        return symbols
