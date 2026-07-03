from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Dict, Optional

from src.schemas.events import AssetClass, Exchange


class InstrumentType(StrEnum):
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    COMMODITY = "COMMODITY"
    CURRENCY = "CURRENCY"
    INDEX = "INDEX"


EXCHANGE_SEGMENT_MAP: dict[str, str] = {
    "NSE": "CASH",
    "BSE": "CASH",
    "NFO": "DERIVATIVES",
    "MCX": "COMMODITY",
    "CDS": "CURRENCY",
    "INDICES": "INDEX",
}

EXCHANGE_DEFAULT_ASSET_CLASS: dict[str, AssetClass] = {
    "NSE": AssetClass.EQUITY,
    "BSE": AssetClass.EQUITY,
    "NFO": AssetClass.EQUITY,
    "MCX": AssetClass.COMMODITY,
    "CDS": AssetClass.CURRENCY,
    "INDICES": AssetClass.INDEX,
}


@dataclass
class InstrumentMetadata:
    symbol: str
    exchange: Exchange
    segment: str
    asset_class: AssetClass
    instrument_type: InstrumentType
    lot_size: int | None = None
    tick_size: float = 0.05
    freeze_qty: int | None = None
    margin_model: str | None = None
    currency: str = "INR"
    expiry: str | None = None

    def requires_lot_size_validation(self) -> bool:
        return self.instrument_type in (InstrumentType.FUTURE, InstrumentType.OPTION, InstrumentType.COMMODITY)

    @property
    def key(self) -> str:
        return f"{self.exchange.value}:{self.symbol}"


_DERIVATIVE_EXCHANGES = frozenset({"NFO", "MCX", "CDS"})


class InstrumentRegistry:
    _instruments: dict[str, InstrumentMetadata] = {}

    @classmethod
    def register(cls, meta: InstrumentMetadata) -> None:
        cls._instruments[meta.key] = meta

    @classmethod
    def get(cls, symbol: str, exchange: str) -> InstrumentMetadata | None:
        return cls._instruments.get(f"{exchange.upper()}:{symbol.upper()}")

    @classmethod
    def resolve(
        cls,
        symbol: str,
        exchange: str,
        instrument_type: InstrumentType | None = None,
    ) -> InstrumentMetadata:
        cached = cls.get(symbol, exchange)
        if cached is not None:
            return cached
        exc = Exchange(exchange.upper())
        seg = EXCHANGE_SEGMENT_MAP.get(exchange.upper(), "CASH")
        ac = EXCHANGE_DEFAULT_ASSET_CLASS.get(exchange.upper(), AssetClass.EQUITY)
        it = instrument_type or cls._default_instrument_type(exchange)
        meta = InstrumentMetadata(
            symbol=symbol.upper(),
            exchange=exc,
            segment=seg,
            asset_class=ac,
            instrument_type=it,
        )
        cls.register(meta)
        return meta

    @classmethod
    def _default_instrument_type(cls, exchange: str) -> InstrumentType:
        mapping = {
            "NSE": InstrumentType.EQUITY,
            "BSE": InstrumentType.EQUITY,
            "NFO": InstrumentType.FUTURE,
            "MCX": InstrumentType.COMMODITY,
            "CDS": InstrumentType.CURRENCY,
            "INDICES": InstrumentType.INDEX,
        }
        return mapping.get(exchange.upper(), InstrumentType.EQUITY)

    @classmethod
    def clear(cls) -> None:
        cls._instruments.clear()

    @classmethod
    def all(cls) -> dict[str, InstrumentMetadata]:
        return dict(cls._instruments)

    @classmethod
    def lot_size_for(cls, symbol: str, exchange: str) -> int | None:
        meta = cls.get(symbol, exchange)
        if meta is None:
            return None
        return meta.lot_size if meta.requires_lot_size_validation() else None


def register_nse_fo_instruments() -> None:
    from src.risk.nse_lot_sizes import NSE_LOT_SIZES

    for symbol, lot_size in NSE_LOT_SIZES.items():
        meta = InstrumentMetadata(
            symbol=symbol,
            exchange=Exchange.NFO,
            segment="DERIVATIVES",
            asset_class=AssetClass.EQUITY,
            instrument_type=InstrumentType.FUTURE,
            lot_size=lot_size,
            tick_size=0.05,
        )
        InstrumentRegistry.register(meta)
        meta_eq = InstrumentMetadata(
            symbol=symbol,
            exchange=Exchange.NSE,
            segment="CASH",
            asset_class=AssetClass.EQUITY,
            instrument_type=InstrumentType.EQUITY,
            lot_size=None,
            tick_size=0.05,
        )
        InstrumentRegistry.register(meta_eq)


def register_mcx_instruments() -> None:
    from src.risk.nse_lot_sizes import MCX_LOT_SIZES

    for symbol, lot_size in MCX_LOT_SIZES.items():
        meta = InstrumentMetadata(
            symbol=symbol,
            exchange=Exchange.MCX,
            segment="COMMODITY",
            asset_class=AssetClass.COMMODITY,
            instrument_type=InstrumentType.COMMODITY,
            lot_size=lot_size,
        )
        InstrumentRegistry.register(meta)


def load_default_instruments() -> None:
    if InstrumentRegistry._instruments:
        return
    register_nse_fo_instruments()
    register_mcx_instruments()
