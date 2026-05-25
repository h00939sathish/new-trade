from __future__ import annotations

from dataclasses import dataclass, field
from math import floor


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    quantity: float
    price: float
    sector: str = "UNKNOWN"

    @property
    def market_value(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True)
class RiskLimits:
    max_single_position_pct: float = 0.25
    max_sector_exposure_pct: float = 0.35
    max_drawdown_pct: float = 0.15
    max_var_pct: float = 0.05


@dataclass(frozen=True)
class RiskBreach:
    name: str
    observed: float
    limit: float
    details: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioRiskReport:
    total_value: float
    position_exposure_pct: dict[str, float]
    sector_exposure_pct: dict[str, float]
    historical_var: float
    max_drawdown: float
    breaches: list[RiskBreach]


def compute_historical_var(returns: list[float], confidence: float = 0.95) -> float:
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    tail_probability = max(0.0, min(1.0, 1.0 - confidence))
    index = max(0, min(len(sorted_returns) - 1, floor(len(sorted_returns) * tail_probability)))
    return round(max(0.0, -sorted_returns[index]), 10)


def compute_max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    return max_drawdown


def compute_portfolio_risk(
    positions: list[PortfolioPosition],
    equity_curve: list[float],
    returns: list[float],
    limits: RiskLimits | None = None,
) -> PortfolioRiskReport:
    limits = limits or RiskLimits()
    total_value = sum(position.market_value for position in positions)
    if total_value <= 0:
        return PortfolioRiskReport(
            total_value=0.0,
            position_exposure_pct={},
            sector_exposure_pct={},
            historical_var=0.0,
            max_drawdown=0.0,
            breaches=[],
        )

    position_exposure = {
        position.symbol: position.market_value / total_value for position in positions
    }
    sector_values: dict[str, float] = {}
    for position in positions:
        current_sector_value = sector_values.get(position.sector, 0.0)
        sector_values[position.sector] = current_sector_value + position.market_value
    sector_exposure = {
        sector: value / total_value for sector, value in sector_values.items()
    }
    historical_var = compute_historical_var(returns)
    max_drawdown = compute_max_drawdown(equity_curve)
    breaches = _find_breaches(
        position_exposure,
        sector_exposure,
        historical_var,
        max_drawdown,
        limits,
    )

    return PortfolioRiskReport(
        total_value=total_value,
        position_exposure_pct=position_exposure,
        sector_exposure_pct=sector_exposure,
        historical_var=historical_var,
        max_drawdown=max_drawdown,
        breaches=breaches,
    )


def _find_breaches(
    position_exposure: dict[str, float],
    sector_exposure: dict[str, float],
    historical_var: float,
    max_drawdown: float,
    limits: RiskLimits,
) -> list[RiskBreach]:
    breaches: list[RiskBreach] = []
    for symbol, observed in position_exposure.items():
        if observed > limits.max_single_position_pct:
            breaches.append(
                RiskBreach(
                    name="single_position_concentration",
                    observed=observed,
                    limit=limits.max_single_position_pct,
                    details={"symbol": symbol},
                )
            )
    for sector, observed in sector_exposure.items():
        if observed > limits.max_sector_exposure_pct:
            breaches.append(
                RiskBreach(
                    name="sector_concentration",
                    observed=observed,
                    limit=limits.max_sector_exposure_pct,
                    details={"sector": sector},
                )
            )
    if max_drawdown > limits.max_drawdown_pct:
        breaches.append(
            RiskBreach(
                name="max_drawdown",
                observed=max_drawdown,
                limit=limits.max_drawdown_pct,
            )
        )
    if historical_var > limits.max_var_pct:
        breaches.append(
            RiskBreach(
                name="historical_var",
                observed=historical_var,
                limit=limits.max_var_pct,
            )
        )
    return breaches
