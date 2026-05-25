from src.risk.analytics import (
    PortfolioPosition,
    RiskLimits,
    compute_historical_var,
    compute_max_drawdown,
    compute_portfolio_risk,
)


def test_historical_var_uses_left_tail_loss_at_confidence_level():
    returns = [0.02, -0.01, -0.05, 0.03, -0.02, -0.10, 0.01, -0.03, 0.04, -0.04]

    assert compute_historical_var(returns, confidence=0.95) == 0.10


def test_max_drawdown_uses_peak_to_trough_decline():
    equity_curve = [100.0, 120.0, 90.0, 110.0, 80.0, 130.0]

    assert round(compute_max_drawdown(equity_curve), 4) == 0.3333


def test_portfolio_risk_reports_concentration_sector_exposure_and_breaches():
    report = compute_portfolio_risk(
        positions=[
            PortfolioPosition("RELIANCE", quantity=10, price=100.0, sector="Energy"),
            PortfolioPosition("TCS", quantity=5, price=100.0, sector="IT"),
            PortfolioPosition("INFY", quantity=5, price=100.0, sector="IT"),
        ],
        equity_curve=[2_000.0, 2_100.0, 1_700.0],
        returns=[0.01, -0.04, -0.02, -0.08, 0.03],
        limits=RiskLimits(
            max_single_position_pct=0.40,
            max_sector_exposure_pct=0.45,
            max_drawdown_pct=0.10,
            max_var_pct=0.05,
        ),
    )

    assert report.total_value == 2_000.0
    assert report.position_exposure_pct["RELIANCE"] == 0.50
    assert report.sector_exposure_pct["IT"] == 0.50
    assert report.max_drawdown == 0.19047619047619047
    assert report.historical_var == 0.08
    assert {breach.name for breach in report.breaches} == {
        "single_position_concentration",
        "sector_concentration",
        "max_drawdown",
        "historical_var",
    }


def test_portfolio_risk_handles_empty_inputs():
    report = compute_portfolio_risk(positions=[], equity_curve=[], returns=[])

    assert report.total_value == 0.0
    assert report.position_exposure_pct == {}
    assert report.sector_exposure_pct == {}
    assert report.historical_var == 0.0
    assert report.max_drawdown == 0.0
    assert report.breaches == []
