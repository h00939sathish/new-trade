import math
from typing import Any

RISK_PER_TRADE = 0.005
MAX_COMBINED_RISK = 0.01
DAILY_LOSS_LIMIT = 0.02


def calculate_oanda_units(
    equity_usd: float,
    entry_price: float,
    stop_price: float,
    instrument_meta: dict[str, Any],
) -> int:
    risk_budget = equity_usd * RISK_PER_TRADE
    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit <= 0:
        return 0
    raw_units = risk_budget / risk_per_unit
    precision = instrument_meta.get("trade_units_precision", 0)
    factor = 10 ** precision
    units = int(math.floor(raw_units * factor) / factor)
    min_size = instrument_meta.get("minimum_trade_size", 1)
    if units < min_size:
        return 0
    return units


def validate_oanda_order(
    equity_usd: float,
    units: int,
    entry_price: float,
    stop_price: float,
    instrument_meta: dict[str, Any],
    combined_risk: float,
) -> tuple[bool, str]:
    if units <= 0:
        return False, "Units must be positive"
    if entry_price <= 0 or stop_price <= 0:
        return False, "Invalid price or stop"
    if abs(entry_price - stop_price) <= 0:
        return False, "Entry and stop must differ"
    if combined_risk >= MAX_COMBINED_RISK:
        return False, f"Combined open risk {combined_risk:.4f} exceeds {MAX_COMBINED_RISK}"
    risk_budget = equity_usd * RISK_PER_TRADE
    risk_per_unit = abs(entry_price - stop_price)
    new_risk = (units * risk_per_unit) / equity_usd
    if combined_risk + new_risk > MAX_COMBINED_RISK:
        return False, "New trade would exceed max combined risk"
    min_size = instrument_meta.get("minimum_trade_size", 1)
    if units < min_size:
        return False, f"Units {units} below minimum {min_size}"
    return True, "OK"
