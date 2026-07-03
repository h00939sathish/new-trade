from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.risk.instrument_metadata import (
    InstrumentRegistry,
    InstrumentType,
    load_default_instruments,
)


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def validate_order(
    symbol: str,
    quantity: int,
    exchange: str,
    instrument_type: InstrumentType | None = None,
) -> ValidationResult:
    """Validate an order against exchange-specific trading rules.

    This is the single entry point for structural order validation.
    It checks:

      - Lot size constraints (FUTURE/OPTION/COMMODITY only)
      - Minimum contract size for derivatives
      - Quantity > 0

    Cash equity trades (EQUITY type) are never subject to lot size
    constraints regardless of the exchange value — a RELIANCE buy on
    NSE can be any number of shares.
    """
    if quantity <= 0:
        return ValidationResult(valid=False, reason="Quantity must be positive")

    load_default_instruments()

    meta = InstrumentRegistry.resolve(symbol, exchange, instrument_type)

    if not meta.requires_lot_size_validation():
        return ValidationResult(valid=True, reason="No lot size constraint for this instrument type")

    if meta.lot_size is None or meta.lot_size <= 0:
        return ValidationResult(valid=True, reason="No lot size defined")

    if quantity % meta.lot_size != 0:
        contracts = quantity // meta.lot_size
        remainder = quantity % meta.lot_size
        return ValidationResult(
            valid=False,
            reason=(
                f"Quantity {quantity} is not a multiple of lot size {meta.lot_size} "
                f"for {symbol} on {exchange} ({meta.instrument_type.value}). "
                f"Nearest valid quantities: {contracts * meta.lot_size} ({contracts} lot(s)) "
                f"or {(contracts + 1) * meta.lot_size} ({contracts + 1} lot(s))."
            ),
            details={
                "symbol": symbol,
                "exchange": exchange,
                "instrument_type": meta.instrument_type.value,
                "lot_size": meta.lot_size,
                "quantity": quantity,
                "contracts": contracts,
                "remainder": remainder,
            },
        )

    return ValidationResult(
        valid=True,
        reason=f"Quantity {quantity} is {quantity // meta.lot_size} lot(s) of {meta.lot_size}",
        details={
            "symbol": symbol,
            "exchange": exchange,
            "instrument_type": meta.instrument_type.value,
            "lot_size": meta.lot_size,
            "contracts": quantity // meta.lot_size,
        },
    )
