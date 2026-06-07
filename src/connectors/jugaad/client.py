import logging
from datetime import date
from typing import Any

logger = logging.getLogger("connector.jugaad.client")


class JugaadError(Exception):
    pass


class JugaadClient:
    def __init__(self):
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        logger.info("Jugaad client ready (NSE bhavcopy-based)")

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        return {}

    async def get_historical(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, Any]]:
        try:
            from jugaad_data.nse import stock_df

            df = stock_df(symbol=symbol, from_date=from_date, to_date=to_date)
            candles = []
            for _, row in df.iterrows():
                ts = row.get("DATE")
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                candles.append(
                    {
                        "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "open": float(row.get("OPEN", 0)),
                        "high": float(row.get("HIGH", 0)),
                        "low": float(row.get("LOW", 0)),
                        "close": float(row.get("CLOSE", 0)),
                        "volume": int(row.get("VOLUME", 0)),
                        "ltp": float(row.get("LTP", 0)),
                        "vwap": float(row.get("VWAP", 0)),
                    }
                )
            return candles
        except Exception as e:
            raise JugaadError(f"Historical data failed for {symbol}: {e}")

    async def search_symbols(self, query: str) -> list[dict[str, Any]]:
        try:
            from datetime import date, timedelta

            from jugaad_data.nse import stock_df

            today = date.today()
            df = stock_df(symbol=query.upper(), from_date=today - timedelta(days=5), to_date=today)
            symbols = df["SYMBOL"].unique().tolist() if "SYMBOL" in df.columns else [query.upper()]
            return [{"symbol": s, "name": s} for s in symbols[:20]]
        except Exception:
            return [{"symbol": query.upper(), "name": query.upper()}]

    async def get_ltp(self, instruments: list[str]) -> dict[str, Any]:
        """Get live last traded prices via Yahoo Finance."""
        try:
            from src.connectors.yahoo import get_ltp_yahoo

            return await get_ltp_yahoo(instruments)
        except Exception as e:
            logger.warning("Yahoo LTP fallback failed: %s", e)
            return {}
