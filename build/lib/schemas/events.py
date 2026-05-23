import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventType(StrEnum):
    TICK = "market.tick"
    OHLCV = "market.ohlcv"
    SIGNAL = "signal.generated"
    ORDER_CREATED = "order.created"
    ORDER_ACCEPTED = "order.accepted"
    ORDER_REJECTED = "order.rejected"
    ORDER_CANCELLED = "order.cancelled"
    FILL = "order.fill"
    RISK_CHECK = "risk.check"
    RISK_BREACH = "risk.breach"
    PORTFOLIO_UPDATE = "portfolio.update"
    PORTFOLIO_REBALANCE = "portfolio.rebalance"
    SYSTEM_HEALTH = "system.health"
    SYSTEM_ERROR = "system.error"
    SYSTEM_STATE = "system.state"
    AGENT_STATUS = "agent.status"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    SL = "sl"
    SL_M = "sl_m"


class OrderStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"


class ProductType(StrEnum):
    CNC = "cnc"
    NRML = "nrml"
    MIS = "mis"


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    MCX = "MCX"
    CDS = "CDS"


class EventMetadata(BaseModel):
    producer: str
    agent_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    version: int = 1


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: EventType
    stream: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any]
    metadata: EventMetadata
    position: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls.model_validate(data)


class MarketDataEvent(Event):
    instrument: str
    exchange: Exchange

    @classmethod
    def create(
        cls,
        instrument: str,
        exchange: Exchange,
        data: dict[str, Any],
        producer: str = "market_intel",
        agent_id: str | None = None,
    ) -> "MarketDataEvent":
        return cls(
            event_type=EventType.TICK,
            stream=f"market.{exchange.value}.{instrument}",
            instrument=instrument,
            exchange=exchange,
            data=data,
            metadata=EventMetadata(producer=producer, agent_id=agent_id),
        )


class OHLCVEvent(Event):
    instrument: str
    exchange: Exchange
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    oi: float | None = None

    @classmethod
    def create(
        cls,
        instrument: str,
        exchange: Exchange,
        interval: str,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        oi: float | None = None,
        producer: str = "market_intel",
    ) -> "OHLCVEvent":
        return cls(
            event_type=EventType.OHLCV,
            stream=f"ohlcv.{exchange.value}.{instrument}.{interval}",
            instrument=instrument,
            exchange=exchange,
            interval=interval,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
            oi=oi,
            data={
                "instrument": instrument,
                "exchange": exchange.value,
                "interval": interval,
                "open": open,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "oi": oi,
            },
            metadata=EventMetadata(producer=producer),
        )


class TickEvent(Event):
    instrument: str
    exchange: Exchange
    last_price: float
    volume: int | None = None
    bid: float | None = None
    ask: float | None = None

    @classmethod
    def create(
        cls,
        instrument: str,
        exchange: Exchange,
        last_price: float,
        volume: int | None = None,
        bid: float | None = None,
        ask: float | None = None,
        producer: str = "market_intel",
    ) -> "TickEvent":
        return cls(
            event_type=EventType.TICK,
            stream=f"tick.{exchange.value}.{instrument}",
            instrument=instrument,
            exchange=exchange,
            last_price=last_price,
            volume=volume,
            bid=bid,
            ask=ask,
            data={
                "instrument": instrument,
                "exchange": exchange.value,
                "last_price": last_price,
                "volume": volume,
                "bid": bid,
                "ask": ask,
            },
            metadata=EventMetadata(producer=producer),
        )


class SignalEvent(Event):
    instrument: str
    strategy: str
    direction: Literal["long", "short", "neutral"]
    confidence: float
    price: float | None = None
    exchange: Exchange = Exchange.NSE

    @classmethod
    def create(
        cls,
        instrument: str,
        strategy: str,
        direction: Literal["long", "short", "neutral"],
        confidence: float,
        price: float | None = None,
        features: dict[str, Any] | None = None,
        exchange: Exchange = Exchange.NSE,
        producer: str = "strategy_gen",
    ) -> "SignalEvent":
        data = {
            "instrument": instrument,
            "strategy": strategy,
            "direction": direction,
            "confidence": confidence,
            "price": price,
            "exchange": exchange.value,
            "features": features or {},
        }
        return cls(
            event_type=EventType.SIGNAL,
            stream=f"signal.{strategy}.{instrument}",
            instrument=instrument,
            strategy=strategy,
            direction=direction,
            confidence=confidence,
            price=price,
            exchange=exchange,
            data=data,
            metadata=EventMetadata(producer=producer),
        )


class OrderEvent(Event):
    order_id: str | None = None
    instrument: str
    exchange: Exchange
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float | None = None
    trigger_price: float | None = None
    product: ProductType
    status: OrderStatus
    variety: str = "regular"

    @classmethod
    def create(
        cls,
        instrument: str,
        exchange: Exchange,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        product: ProductType,
        price: float | None = None,
        trigger_price: float | None = None,
        variety: str = "regular",
        order_id: str | None = None,
        status: OrderStatus = OrderStatus.PENDING,
        producer: str = "execution",
    ) -> "OrderEvent":
        data = {
            "order_id": order_id,
            "instrument": instrument,
            "exchange": exchange.value,
            "side": side.value,
            "order_type": order_type.value,
            "quantity": quantity,
            "price": price,
            "trigger_price": trigger_price,
            "product": product.value,
            "status": status.value,
            "variety": variety,
        }
        return cls(
            event_type=EventType.ORDER_CREATED if status == OrderStatus.PENDING else EventType.ORDER_ACCEPTED,
            stream=f"order.{instrument}",
            order_id=order_id,
            instrument=instrument,
            exchange=exchange,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            product=product,
            status=status,
            variety=variety,
            data=data,
            metadata=EventMetadata(producer=producer),
        )


class FillEvent(Event):
    order_id: str
    instrument: str
    exchange: Exchange
    side: OrderSide
    fill_price: float
    fill_quantity: int
    fill_timestamp: datetime
    trade_id: str | None = None

    @classmethod
    def create(
        cls,
        order_id: str,
        instrument: str,
        exchange: Exchange,
        side: OrderSide,
        fill_price: float,
        fill_quantity: int,
        fill_timestamp: datetime | None = None,
        trade_id: str | None = None,
        producer: str = "execution",
    ) -> "FillEvent":
        return cls(
            event_type=EventType.FILL,
            stream=f"fill.{instrument}",
            order_id=order_id,
            instrument=instrument,
            exchange=exchange,
            side=side,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
            fill_timestamp=fill_timestamp or datetime.now(UTC),
            trade_id=trade_id,
            data={
                "order_id": order_id,
                "instrument": instrument,
                "exchange": exchange.value,
                "side": side.value,
                "fill_price": fill_price,
                "fill_quantity": fill_quantity,
                "fill_timestamp": (fill_timestamp or datetime.now(UTC)).isoformat(),
                "trade_id": trade_id,
            },
            metadata=EventMetadata(producer=producer),
        )


class RiskCheckEvent(Event):
    check_name: str
    passed: bool
    instrument: str | None = None
    details: dict[str, Any] = {}

    @classmethod
    def create(
        cls,
        check_name: str,
        passed: bool,
        instrument: str | None = None,
        details: dict[str, Any] | None = None,
        producer: str = "risk_mgmt",
    ) -> "RiskCheckEvent":
        return cls(
            event_type=EventType.RISK_BREACH if not passed else EventType.RISK_CHECK,
            stream="risk" if passed else "risk.breach",
            check_name=check_name,
            passed=passed,
            instrument=instrument,
            details=details or {},
            data={
                "check_name": check_name,
                "passed": passed,
                "instrument": instrument,
                "details": details or {},
            },
            metadata=EventMetadata(producer=producer),
        )


class PortfolioEvent(Event):
    total_value: float
    cash: float
    pnl: float
    exposure: float
    positions: list[dict[str, Any]] = []

    @classmethod
    def create(
        cls,
        total_value: float,
        cash: float,
        pnl: float,
        exposure: float,
        positions: list[dict[str, Any]] | None = None,
        producer: str = "portfolio_opt",
    ) -> "PortfolioEvent":
        return cls(
            event_type=EventType.PORTFOLIO_UPDATE,
            stream="portfolio",
            total_value=total_value,
            cash=cash,
            pnl=pnl,
            exposure=exposure,
            positions=positions or [],
            data={
                "total_value": total_value,
                "cash": cash,
                "pnl": pnl,
                "exposure": exposure,
                "positions": positions or [],
            },
            metadata=EventMetadata(producer=producer),
        )


class SystemEvent(Event):
    @classmethod
    def health(cls, component: str, status: str, details: dict[str, Any] | None = None) -> "SystemEvent":
        return cls(
            event_type=EventType.SYSTEM_HEALTH,
            stream=f"system.health.{component}",
            data={
                "component": component,
                "status": status,
                "details": details or {},
            },
            metadata=EventMetadata(producer="system"),
        )

    @classmethod
    def error(cls, component: str, error: str, fatal: bool = False) -> "SystemEvent":
        return cls(
            event_type=EventType.SYSTEM_ERROR,
            stream="system.error",
            data={
                "component": component,
                "error": error,
                "fatal": fatal,
            },
            metadata=EventMetadata(producer="system"),
        )
