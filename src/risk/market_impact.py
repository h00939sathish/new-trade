import math


class MarketImpactModel:
    """Square-root market impact model.

    Estimates the price impact of a large order using the Almgren-Chriss
    square-root formula:

        impact_bps = alpha * sigma * sqrt(qty / ADV)

    where:
    - sigma    : daily volatility (as decimal, e.g. 0.02 for 2 %)
    - qty      : order size in shares
    - ADV      : average daily volume in shares
    - alpha    : calibration constant (default 1.0)
    """

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha

    def estimate_impact_bps(
        self,
        order_qty: int,
        avg_daily_volume: float,
        daily_volatility: float,
    ) -> float:
        """Return estimated impact in basis points."""
        if avg_daily_volume <= 0 or order_qty <= 0:
            return 0.0
        participation = order_qty / avg_daily_volume
        return self.alpha * daily_volatility * 10_000 * math.sqrt(participation)

    def is_significant(
        self,
        order_qty: int,
        avg_daily_volume: float,
        daily_volatility: float,
        threshold_bps: float = 20.0,
    ) -> tuple[bool, float]:
        """Check whether impact exceeds a threshold. Returns ``(is_significant, impact_bps)``."""
        impact = self.estimate_impact_bps(order_qty, avg_daily_volume, daily_volatility)
        return impact > threshold_bps, impact
