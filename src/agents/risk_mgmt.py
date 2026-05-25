from datetime import UTC, datetime
from typing import Any

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.schemas.events import (
    Event,
    EventType,
    RiskCheckEvent,
)


class RiskManagementAgent(BaseAgent):
    def __init__(self, event_store=None):
        super().__init__("risk_mgmt", event_store=event_store)
        self._max_position_size = settings.risk_max_position_size
        self._max_drawdown = settings.risk_max_drawdown_pct
        self._max_leverage = settings.risk_max_leverage
        self._max_order_value = settings.risk_max_order_value
        self._positions: dict[str, float] = {}
        self._orders_today: int = 0
        self._order_value_today: float = 0.0
        self._peak_value: float | None = None
        self._current_value: float | None = None
        self._last_reset: datetime | None = None

    async def on_start(self) -> None:
        self.logger.info("Risk Management Agent initializing")
        self.subscribe_signals()
        self.subscribe_orders()
        self.subscribe_risk()
        self.subscribe(EventType.FILL)
        self.subscribe(EventType.PORTFOLIO_UPDATE)
        self.subscribe(EventType.TICK)
        self.logger.info(
            "Risk limits: max_pos=%.0f, max_drawdown=%.0f%%, max_leverage=%.1fx, max_order=%.0f",
            self._max_position_size,
            self._max_drawdown * 100,
            self._max_leverage,
            self._max_order_value,
        )

    async def on_event(self, event: Event) -> None:
        # Auto-reset daily limits on date change
        self._maybe_reset_daily_limits()

        match event.event_type:
            case EventType.TICK:
                self._track_price(event)
            case EventType.SIGNAL:
                await self._validate_signal(event)
            case EventType.ORDER_CREATED:
                await self._validate_order(event)
            case EventType.FILL:
                self._update_position(event)
            case EventType.PORTFOLIO_UPDATE:
                self._update_portfolio(event)
            case EventType.RISK_BREACH:
                self.logger.warning("Risk breach: %s", event.data)

    async def _validate_signal(self, event: Event) -> None:
        signal = event.data
        instrument = signal.get("instrument", "")
        direction = signal.get("direction", "neutral")
        confidence = signal.get("confidence", 0.0)

        # Direction-aware exposure check: sell orders reducing positions
        # should bypass the exposure limit (fix 1.2)
        is_reducing = (
            direction == "short"
            and self._positions.get(instrument, 0) > 0
        )

        checks = [
            await self._check_instrument_risk(instrument, direction, confidence),
            await self._check_drawdown_risk(),
            await self._check_var_risk(instrument),
        ]
        # Only check exposure for orders that INCREASE position
        if not is_reducing:
            checks.append(await self._check_exposure_risk(instrument))

        all_passed = all(c["passed"] for c in checks)

        # Inject signal_event_id for correlation with ExecutionAgent (fix 1.1)
        signal_with_id = {**signal, "_signal_event_id": event.event_id}

        risk_event = RiskCheckEvent.create(
            check_name="signal_validation",
            passed=all_passed,
            instrument=instrument,
            details={"signal": signal_with_id, "checks": checks},
            producer=self.name,
        )
        await self.emit(risk_event)
        if not all_passed:
            self.logger.warning(
                "Signal REJECTED: %s %s (confidence=%.2f)",
                instrument, direction, confidence,
            )
            for check in checks:
                if not check["passed"]:
                    self.logger.warning("  Failed check: %s", check["name"])
        else:
            self.logger.info(
                "Signal APPROVED: %s %s (confidence=%.2f, reducing=%s)",
                instrument, direction, confidence, is_reducing,
            )

    async def _validate_order(self, event: Event) -> None:
        order_data = event.data
        quantity = order_data.get("quantity", 0)
        price = order_data.get("price", 0) or 0
        side = order_data.get("side", "buy")
        order_value = quantity * price

        # Sell orders that reduce existing positions should not be blocked
        # by exposure limits (fix 1.2)
        instrument = order_data.get("instrument", "")
        is_reducing = (
            side in ("sell", "SELL")
            and self._positions.get(instrument, 0) > 0
        )

        checks: list[dict[str, Any]] = [
            self._check("order_size", order_value <= self._max_order_value, {
                "order_value": order_value, "max": self._max_order_value,
            }),
            self._check("daily_order_value", self._order_value_today + order_value <= self._max_position_size * 3, {
                "daily_total": self._order_value_today + order_value, "limit": self._max_position_size * 3,
            }),
        ]
        # Only check exposure for orders that INCREASE position
        if not is_reducing:
            checks.append(self._check("exposure", self._get_total_exposure() + order_value <= self._max_position_size, {
                "total_exposure": self._get_total_exposure() + order_value, "max": self._max_position_size,
            }))

        all_passed = all(c["passed"] for c in checks)
        risk_event = RiskCheckEvent.create(
            check_name="order_validation",
            passed=all_passed,
            instrument=instrument,
            details={"order": order_data, "checks": checks},
            producer=self.name,
        )
        await self.emit(risk_event)
        if all_passed:
            self._orders_today += 1
            self._order_value_today += order_value
            self.logger.info("Order APPROVED: %s", order_data.get("order_id", "unknown"))

    def _update_position(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        quantity = event.data.get("fill_quantity", 0)
        side = event.data.get("side", "buy")
        if side == "buy":
            self._positions[instrument] = self._positions.get(instrument, 0) + quantity
        else:
            self._positions[instrument] = self._positions.get(instrument, 0) - quantity

    def _update_portfolio(self, event: Event) -> None:
        self._current_value = event.data.get("total_value")
        if self._peak_value is None or (self._current_value and self._current_value > self._peak_value):
            self._peak_value = self._current_value

    def get_position(self, instrument: str) -> float:
        return self._positions.get(instrument, 0.0)

    def get_total_exposure(self) -> float:
        return sum(abs(v) for v in self._positions.values())

    def _get_total_exposure(self) -> float:
        return self.get_total_exposure()

    async def _check_instrument_risk(
        self,
        instrument: str,
        direction: str,
        confidence: float,
    ) -> dict[str, Any]:
        current_pos = abs(self._positions.get(instrument, 0))
        return self._check("instrument_exposure", current_pos < self._max_position_size, {
            "instrument": instrument,
            "current_position": current_pos,
            "max": self._max_position_size,
            "signal_direction": direction,
            "confidence": confidence,
        })

    async def _check_exposure_risk(self, instrument: str) -> dict[str, Any]:
        total = self._get_total_exposure()
        return self._check("total_exposure", total < self._max_position_size, {
            "total_exposure": total,
            "max": self._max_position_size,
        })

    async def _check_drawdown_risk(self) -> dict[str, Any]:
        if self._peak_value is None or self._current_value is None:
            return self._check("drawdown", True, {"reason": "no portfolio data yet"})
        drawdown = (self._peak_value - self._current_value) / self._peak_value
        return self._check("drawdown", drawdown <= self._max_drawdown, {
            "drawdown_pct": drawdown,
            "max_allowed_pct": self._max_drawdown,
            "peak_value": self._peak_value,
            "current_value": self._current_value,
        })

    async def _check_var_risk(self, instrument: str) -> dict[str, Any]:
        from collections import deque
        if not hasattr(self, "_price_history"):
            self._price_history: dict[str, deque[float]] = {}
        history = self._price_history.get(instrument, [])
        if len(history) < 20:
            return self._check("var_95", True, {"reason": "insufficient data"})
        returns = []
        h = list(history)
        for i in range(1, len(h)):
            if h[i-1] > 0:
                returns.append((h[i] - h[i-1]) / h[i-1])
        if len(returns) < 20:
            return self._check("var_95", True, {"reason": "insufficient returns"})
        sorted_ret = sorted(returns)
        var_idx = max(0, int(len(sorted_ret) * 0.05) - 1)
        var_95 = abs(sorted_ret[var_idx])
        position_value = abs(self._positions.get(instrument, 0)) * 1000
        var_loss = position_value * var_95
        max_var_loss = self._max_position_size * 0.02
        return self._check("var_95", var_loss <= max_var_loss, {
            "var_95_pct": var_95,
            "position_value": position_value,
            "var_loss": var_loss,
            "max_var_loss": max_var_loss,
            "returns_sample": len(returns),
        })

    def _check(self, name: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "passed": passed, "details": details}

    def _track_price(self, event: Event) -> None:
        from collections import deque
        if not hasattr(self, "_price_history"):
            self._price_history: dict[str, deque[float]] = {}
        instrument = event.data.get("instrument", "")
        price = event.data.get("last_price") or event.data.get("close")
        if price is not None:
            if instrument not in self._price_history:
                self._price_history[instrument] = deque(maxlen=100)
            self._price_history[instrument].append(float(price))

    def _maybe_reset_daily_limits(self) -> None:
        """Auto-reset daily limits if the date has changed since last reset."""
        now = datetime.now(UTC)
        if self._last_reset is None or self._last_reset.date() != now.date():
            self._orders_today = 0
            self._order_value_today = 0.0
            self._last_reset = now
            self.logger.info("Daily risk limits auto-reset for %s", now.date())

    async def reset_daily_limits(self) -> None:
        """Manual reset (kept for API compatibility)."""
        self._orders_today = 0
        self._order_value_today = 0.0
        self._last_reset = datetime.now(UTC)
        self.logger.info("Daily risk limits reset (manual)")

    async def on_stop(self) -> None:
        self.logger.info("Risk Management Agent stopping")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "open_positions": len(self._positions),
            "total_exposure": self._get_total_exposure(),
            "orders_today": self._orders_today,
            "peak_value": self._peak_value,
            "current_value": self._current_value,
        })
        return base
