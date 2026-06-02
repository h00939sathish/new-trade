import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventType(StrEnum):
    TICK = "market.tick"
    OHLCV = "market.ohlcv"
    SIGNAL = "signal.generated"
    CANDIDATE_SIGNAL = "signal.candidate"
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
    MACRO_SENTIMENT = "macro.sentiment"


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
    correlation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
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
        correlation_id: str | None = None,
    ) -> "MarketDataEvent":
        meta = EventMetadata(producer=producer, agent_id=agent_id)
        if correlation_id:
            meta.correlation_id = correlation_id
        return cls(
            event_type=EventType.TICK,
            stream=f"market.{exchange.value}.{instrument}",
            instrument=instrument,
            exchange=exchange,
            data=data,
            metadata=meta,
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
        correlation_id: str | None = None,
    ) -> "OHLCVEvent":
        meta = EventMetadata(producer=producer)
        if correlation_id:
            meta.correlation_id = correlation_id
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
            metadata=meta,
        )


class TickEvent(Event):
    instrument: str
    exchange: Exchange
    last_price: float
    volume: int | None = None
    bid: float | None = None
    ask: float | None = None
    depth: dict[str, list[dict[str, Any]]] | None = None

    @classmethod
    def create(
        cls,
        instrument: str,
        exchange: Exchange,
        last_price: float,
        volume: int | None = None,
        bid: float | None = None,
        ask: float | None = None,
        depth: dict[str, list[dict[str, Any]]] | None = None,
        producer: str = "market_intel",
        timestamp: datetime | None = None,
        correlation_id: str | None = None,
    ) -> "TickEvent":
        kwargs = {}
        if timestamp is not None:
            kwargs["timestamp"] = timestamp
        meta = EventMetadata(producer=producer)
        if correlation_id:
            meta.correlation_id = correlation_id
        return cls(
            event_type=EventType.TICK,
            stream=f"tick.{exchange.value}.{instrument}",
            instrument=instrument,
            exchange=exchange,
            last_price=last_price,
            volume=volume,
            bid=bid,
            ask=ask,
            depth=depth,
            data={
                "instrument": instrument,
                "exchange": exchange.value,
                "last_price": last_price,
                "volume": volume,
                "bid": bid,
                "ask": ask,
                "depth": depth,
            },
            metadata=meta,
            **kwargs,
        )


class SignalEvent(Event):
    instrument: str
    strategy: str
    direction: Literal["long", "short", "neutral"]
    confidence: float
    price: float | None = None
    exchange: Exchange = Exchange.NSE
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

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
        timestamp: datetime | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        correlation_id: str | None = None,
    ) -> "SignalEvent":
        data = {
            "instrument": instrument,
            "strategy": strategy,
            "direction": direction,
            "confidence": confidence,
            "price": price,
            "exchange": exchange.value,
            "features": features or {},
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        }
        kwargs = {}
        if timestamp is not None:
            kwargs["timestamp"] = timestamp
        meta = EventMetadata(producer=producer)
        if correlation_id:
            meta.correlation_id = correlation_id
        return cls(
            event_type=EventType.SIGNAL,
            stream=f"signal.{strategy}.{instrument}",
            instrument=instrument,
            strategy=strategy,
            direction=direction,
            confidence=confidence,
            price=price,
            exchange=exchange,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            data=data,
            metadata=meta,
            **kwargs,
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
    disclosed_quantity: int | None = None
    signal_id: str | None = None
    strategy: str | None = None

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
        disclosed_quantity: int | None = None,
        producer: str = "execution",
        signal_id: str | None = None,
        strategy: str | None = None,
        correlation_id: str | None = None,
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
            "disclosed_quantity": disclosed_quantity,
            "signal_id": signal_id,
            "strategy": strategy,
        }
        meta = EventMetadata(producer=producer)
        if correlation_id:
            meta.correlation_id = correlation_id
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
            disclosed_quantity=disclosed_quantity,
            signal_id=signal_id,
            strategy=strategy,
            data=data,
            metadata=meta,
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
    signal_id: str | None = None
    strategy: str | None = None
    broker_order_id: str | None = None
    commission: float | None = None
    slippage_bps: float | None = None

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
        signal_id: str | None = None,
        strategy: str | None = None,
        broker_order_id: str | None = None,
        commission: float | None = None,
        slippage_bps: float | None = None,
    ) -> "FillEvent":
        ts = fill_timestamp or datetime.now(UTC)
        return cls(
            event_type=EventType.FILL,
            stream=f"fill.{instrument}",
            order_id=order_id,
            instrument=instrument,
            exchange=exchange,
            side=side,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
            fill_timestamp=ts,
            trade_id=trade_id,
            timestamp=ts,
            signal_id=signal_id,
            strategy=strategy,
            broker_order_id=broker_order_id,
            data={
                "order_id": order_id,
                "instrument": instrument,
                "exchange": exchange.value,
                "side": side.value,
                "fill_price": fill_price,
                "fill_quantity": fill_quantity,
                "fill_timestamp": ts.isoformat(),
                "trade_id": trade_id,
                "signal_id": signal_id,
                "strategy": strategy,
                "broker_order_id": broker_order_id,
                "commission": commission,
                "slippage_bps": slippage_bps,
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
        correlation_id: str | None = None,
    ) -> "RiskCheckEvent":
        meta = EventMetadata(producer=producer)
        if correlation_id:
            meta.correlation_id = correlation_id
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
            metadata=meta,
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


class MacroSentimentEvent(Event):
    geopolitical_score: float
    macro_score: float
    composite_multiplier: float
    rationale: str

    @classmethod
    def create(
        cls,
        geopolitical_score: float,
        macro_score: float,
        composite_multiplier: float,
        rationale: str,
        producer: str = "personas",
    ) -> "MacroSentimentEvent":
        return cls(
            event_type=EventType.MACRO_SENTIMENT,
            stream="macro.sentiment",
            geopolitical_score=geopolitical_score,
            macro_score=macro_score,
            composite_multiplier=composite_multiplier,
            rationale=rationale,
            data={
                "geopolitical_score": geopolitical_score,
                "macro_score": macro_score,
                "composite_multiplier": composite_multiplier,
                "rationale": rationale,
            },
            metadata=EventMetadata(producer=producer),
        )
