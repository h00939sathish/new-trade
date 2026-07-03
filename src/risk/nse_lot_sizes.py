"""Lot sizes for derivatives instruments across exchanges (NSE F&O, MCX).

NSE lot sizes change periodically based on SEBI circulars. The primary source
is the NSE contract specifications page:
https://www.nseindia.com/regulations/market-readiness-fix-file-download

MCX lot sizes are based on MCX contract specifications:
https://www.mcxindia.com/products/gold-futures

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

# MCX commodity lot sizes
# {symbol: lot_size}
MCX_LOT_SIZES: dict[str, int] = {
    "GOLD": 1,        # Gold (1kg) futures — 1 unit per lot
    "GOLDM": 1,       # Gold Mini (100g) — 1 unit per lot
    "GOLDGUINEA": 8,  # Gold Guinea (8g) — 8 units per lot
    "PETROL": 1,
    "CRUDEOIL": 100,
    "NATURALGAS": 1200,
    "SILVER": 30,
    "SILVERM": 5,
    "COPPER": 250,
    "ZINC": 5000,
    "LEAD": 5000,
    "ALUMINIUM": 5000,
}


def get_lot_sizes_for_exchange(exchange: str) -> dict[str, int]:
    """Return the lot size table for a given exchange."""
    if exchange.upper() == "MCX":
        return MCX_LOT_SIZES
    return NSE_LOT_SIZES


def validate_lot_size(
    symbol: str,
    quantity: int,
    exchange: str = "NSE",
) -> dict:
    """Check whether ``quantity`` is a valid multiple of the exchange's lot size.

    Returns a dict with ``valid``, ``lot_size``, and ``message`` keys.
    Instruments not in the lot size table (cash market or unknown) always pass.

    Lot size validation only applies to derivative exchanges (NFO, MCX).
    Cash equity trades on NSE/BSE are not subject to lot size restrictions.
    """
    if exchange.upper() not in ("NFO", "MCX"):
        return {"valid": True, "lot_size": None, "message": ""}
    lot_sizes = get_lot_sizes_for_exchange(exchange)
    lot_size = lot_sizes.get(symbol.upper())
    if lot_size is None:
        return {"valid": True, "lot_size": None, "message": ""}
    if quantity % lot_size != 0:
        return {
            "valid": False,
            "lot_size": lot_size,
            "message": f"Quantity {quantity} is not a multiple of lot size {lot_size} for {symbol} on {exchange}",
        }
    return {
        "valid": True,
        "lot_size": lot_size,
        "message": f"Quantity {quantity} is {quantity // lot_size} lot(s) of {lot_size}",
    }
