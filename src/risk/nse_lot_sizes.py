"""NSE F&O lot sizes for common derivatives instruments.

Lot sizes change periodically based on SEBI circulars. The primary source
is the NSE contract specifications page:
https://www.nseindia.com/regulations/market-readiness-fix-file-download

This table was last reviewed on 2026-06-21.
"""

# {symbol: lot_size}
NSE_LOT_SIZES: dict[str, int] = {
    "RELIANCE": 250,
    "TCS": 150,
    "INFY": 300,
    "HDFCBANK": 200,
    "ICICIBANK": 700,
    "SBIN": 800,
    "BHARTIARTL": 900,
    "ITC": 2000,
    "KOTAKBANK": 400,
    "AXISBANK": 600,
    "LT": 350,
    "WIPRO": 300,
    "HCLTECH": 250,
    "MARUTI": 75,
    "TATAMOTORS": 1500,
    "TATASTEEL": 1000,
    "JSWSTEEL": 1200,
    "POWERGRID": 2000,
    "NTPC": 2000,
    "ONGC": 2000,
    "SUNPHARMA": 350,
    "DRREDDY": 100,
    "CIPLA": 500,
    "HINDUNILVR": 100,
    "NESTLEIND": 25,
    "TITAN": 125,
    "BAJFINANCE": 100,
    "BAJAJFINSV": 200,
    "ASIANPAINT": 150,
    "ULTRACEMCO": 100,
    "GRASIM": 400,
    "ADANIENT": 700,
    "ADANIPORTS": 600,
    "HDFC": 200,
    "DIVISLAB": 150,
    "COALINDIA": 2000,
    "IOC": 2000,
    "BPCL": 2000,
    "HINDALCO": 1000,
    "VEDL": 2000,
    "EICHERMOT": 100,
    "HEROMOTOCO": 200,
    "BAJAJ-AUTO": 100,
    "M&M": 500,
    "TATACONSUM": 600,
    "BRITANNIA": 200,
    "SHREECEM": 50,
    "INDUSINDBK": 400,
    "BANKBARODA": 2000,
    "PIDILITIND": 250,
    "COLPAL": 400,
    "HAL": 400,
    "BEL": 2000,
    "ZOMATO": 2000,
    "TRENT": 300,
    "AVENUE": 400,
}
"""NSE F&O lot sizes keyed by symbol (ticker without exchange suffix)."""


def validate_lot_size(symbol: str, quantity: int) -> tuple[bool, str]:
    """Check whether ``quantity`` is a valid multiple of the NSE lot size.

    Returns ``(is_valid, message)``. Instruments not in the table (cash
    market) always pass.
    """
    lot_size = NSE_LOT_SIZES.get(symbol.upper())
    if lot_size is None:
        return True, ""
    if quantity % lot_size != 0:
        return (
            False,
            f"Quantity {quantity} is not a multiple of lot size {lot_size} for {symbol}",
        )
    return True, f"Quantity {quantity} is {quantity // lot_size} lot(s) of {lot_size}"
