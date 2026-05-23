import logging

import httpx

logger = logging.getLogger("connector.yahoo")

EXCHANGE_MAP = {
    "NSE": ".NS",
    "BSE": ".BO",
}


async def get_ltp_yahoo(instruments: list[str]) -> dict[str, dict[str, float | int | None]]:
    results: dict[str, dict[str, float | int | None]] = {}
    async with httpx.AsyncClient(timeout=10) as http:
        for instr in instruments:
            parts = instr.split(":")
            exchange = parts[0] if len(parts) > 1 else "NSE"
            symbol = parts[1] if len(parts) > 1 else instr
            suffix = EXCHANGE_MAP.get(exchange, "")
            try:
                resp = await http.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}{suffix}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("previousClose")
                volume = meta.get("regularMarketVolume")
                if price is not None:
                    change = (price - prev_close) if prev_close else None
                    change_pct = (change / prev_close * 100) if prev_close and prev_close else None
                    results[instr] = {
                        "last_price": float(price),
                        "volume": int(volume) if volume else None,
                        "open": meta.get("regularMarketOpen"),
                        "high": meta.get("dayHigh"),
                        "low": meta.get("dayLow"),
                        "previous_close": prev_close,
                        "change": change,
                        "change_pct": change_pct,
                    }
            except Exception as e:
                logger.debug("Yahoo Finance LTP failed for %s: %s", instr, e)
    return results


async def get_ltp_yahoo_single(
    symbol: str, exchange: str = "NSE",
) -> dict[str, float | int | None] | None:
    result = await get_ltp_yahoo([f"{exchange}:{symbol}"])
    return result.get(f"{exchange}:{symbol}")
