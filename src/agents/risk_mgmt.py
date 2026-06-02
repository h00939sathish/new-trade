from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.schemas.events import (
    Event,
    EventType,
    RiskCheckEvent,
)
from src.monitoring.latency_tracer import tracer

# IST timezone offset
_IST = timezone(timedelta(hours=5, minutes=30))
# NSE market hours
_MARKET_OPEN_HOUR, _MARKET_OPEN_MIN = 9, 15
_MARKET_CLOSE_HOUR, _MARKET_CLOSE_MIN = 15, 30
# Auto square-off warning before close
_SQUARE_OFF_HOUR, _SQUARE_OFF_MIN = 15, 15


class RiskManagementAgent(BaseAgent):
    def __init__(self, event_store=None):
        super().__init__("risk_mgmt", event_store=event_store)
        self._max_position_size = settings.risk_max_position_size
        self._max_drawdown = settings.risk_max_drawdown_pct
        self._max_leverage = settings.risk_max_leverage
        self._max_order_value = settings.risk_max_order_value
        self._per_trade_loss_cap_pct = settings.risk_per_trade_loss_cap_pct
        self._positions: dict[str, float] = {}
        self._orders_today: int = 0
        self._order_value_today: float = 0.0
        self._peak_value: float | None = None
        self._current_value: float | None = None
        self._last_reset: datetime | None = None
        from src.risk.earnings_filter import EarningsCalendarFilter
        self._earnings_filter = EarningsCalendarFilter(settings.earnings_calendar_path)

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

    def _is_market_hours(self) -> bool:
        """Check if current time is within NSE trading hours (9:15-15:30 IST)."""
        now_ist = datetime.now(_IST)
        market_open = now_ist.replace(
            hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MIN, second=0, microsecond=0,
        )
        market_close = now_ist.replace(
            hour=_MARKET_CLOSE_HOUR, minute=_MARKET_CLOSE_MIN, second=0, microsecond=0,
        )
        return market_open <= now_ist <= market_close

    def _is_square_off_window(self) -> bool:
        """Check if we're in the auto-square-off window (15:15-15:30 IST)."""
        now_ist = datetime.now(_IST)
        square_off = now_ist.replace(
            hour=_SQUARE_OFF_HOUR, minute=_SQUARE_OFF_MIN, second=0, microsecond=0,
        )
        market_close = now_ist.replace(
            hour=_MARKET_CLOSE_HOUR, minute=_MARKET_CLOSE_MIN, second=0, microsecond=0,
        )
        return square_off <= now_ist <= market_close

    async def _validate_signal(self, event: Event) -> None:
        start_time = time.monotonic()
        import time
        signal = event.data
        instrument = signal.get("instrument", "")
        direction = signal.get("direction", "neutral")
        confidence = signal.get("confidence", 0.0)

        # Market hours enforcement: block new entries outside trading hours
        if direction != "neutral" and not self._is_market_hours():
            self.logger.warning(
                "Signal REJECTED: outside market hours (%s %s)", instrument, direction,
            )
            risk_event = RiskCheckEvent.create(
                check_name="signal_validation",
                passed=False,
                instrument=instrument,
                details={"signal": {**signal, "_signal_event_id": event.event_id},
                         "checks": [{"name": "market_hours", "passed": False,
                                      "details": {"reason": "outside NSE trading hours"}}]},
                producer=self.name,
                correlation_id=event.metadata.correlation_id,
            )
            await self.emit(risk_event)
            return

        # Warn during square-off window — only allow closing positions
        if direction != "neutral" and self._is_square_off_window():
            self.logger.warning(
                "Signal REJECTED: in square-off window (15:15-15:30). Only exits allowed. %s %s",
                instrument, direction,
            )
            risk_event = RiskCheckEvent.create(
                check_name="signal_validation",
                passed=False,
                instrument=instrument,
                details={"signal": {**signal, "_signal_event_id": event.event_id},
                         "checks": [{"name": "square_off_window", "passed": False,
                                      "details": {"reason": "square-off window active"}}]},
                producer=self.name,
                correlation_id=event.metadata.correlation_id,
            )
            await self.emit(risk_event)
            return

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
            await self._check_liquidity_risk(instrument),
            await self._check_per_trade_risk(instrument, signal),
            await self._check_max_open_positions_risk(instrument, direction),
            await self._check_earnings_risk(instrument),
            await self._check_correlation_risk(instrument),
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
            correlation_id=event.metadata.correlation_id,
        )
        tracer.record_trace(event.metadata.correlation_id, "risk_mgmt.signal_validation", (time.monotonic() - start_time) * 1000)
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

    async def _check_per_trade_risk(self, instrument: str, signal: dict[str, Any]) -> dict[str, Any]:
        from src.risk.kill_switch import KillSwitch
        ks = KillSwitch()
        capital = ks._initial_capital if ks._initial_capital else 1_000_000.0
        max_loss_allowed = capital * self._per_trade_loss_cap_pct
        
        # Try to estimate potential loss from signal SL and quantity
        price = signal.get("price")
        if not price:
            return self._check("per_trade_loss_cap", True, {"reason": "no_price"})
            
        features = signal.get("features", {})
        atr = features.get("atr", None)
        if atr is None and "votes" in features:
            for strat_data in features["votes"].values():
                strat_feat = strat_data.get("features", {})
                if "atr" in strat_feat and strat_feat["atr"]:
                    atr = strat_feat["atr"]
                    break
                    
        sl_pct = 0.02
        if atr is not None and price > 0:
            sl_pct = min(max((2.0 * atr) / price, 0.005), 0.05)
            
        # Estimate quantity logic used by ExecutionAgent
        volatility = atr if atr else price * 0.02
        stop_distance = volatility * 2.0
        risk_per_trade = capital * 0.01
        
        raw_qty = risk_per_trade / stop_distance if stop_distance > 0 else 0
        max_qty = (capital * 0.05) / price
        quantity = max(1, int(min(raw_qty, max_qty)))
        
        potential_loss = quantity * price * sl_pct
        
        return self._check("per_trade_loss_cap", potential_loss <= max_loss_allowed, {
            "potential_loss": potential_loss,
            "max_loss_allowed": max_loss_allowed,
            "estimated_qty": quantity,
            "estimated_sl_pct": sl_pct
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
        # Use actual last tracked price instead of hardcoded multiplier
        last_price = float(history[-1]) if history else 1000.0
        position_value = abs(self._positions.get(instrument, 0)) * last_price
        var_loss = position_value * var_95
        max_var_loss = self._max_position_size * 0.02
        return self._check("var_95", var_loss <= max_var_loss, {
            "var_95_pct": var_95,
            "position_value": position_value,
            "var_loss": var_loss,
            "max_var_loss": max_var_loss,
            "returns_sample": len(returns),
        })

    async def _check_liquidity_risk(self, instrument: str) -> dict[str, Any]:
        """Check if instrument has sufficient recent volume/liquidity."""
        if not hasattr(self, "_volume_history") or instrument not in self._volume_history:
            # Pass by default if no volume data is available yet
            return self._check("liquidity", True, {"reason": "no_data"})

        vols = self._volume_history[instrument]
        if not vols:
            return self._check("liquidity", True, {"reason": "no_data"})

        avg_vol = sum(vols) / len(vols)
        # Threshold would ideally be configurable; using 1000 for demonstration
        passed = avg_vol > 1000.0 or len(vols) < 10

        return self._check("liquidity", passed, {
            "avg_volume": avg_vol,
            "threshold": 1000.0,
            "samples": len(vols)
        })

    def _check(self, name: str, passed: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"name": name, "passed": passed, "details": details or {}}

    async def _check_max_open_positions_risk(self, instrument: str, direction: str) -> dict[str, Any]:
        if direction == "neutral":
            return self._check("max_open_positions", True)
            
        current_qty = self._positions.get(instrument, 0.0)
        is_new_position = (current_qty == 0.0)
        
        if is_new_position:
            active_positions = [k for k, v in self._positions.items() if v != 0.0]
            if len(active_positions) >= settings.risk_max_open_positions:
                return self._check("max_open_positions", False, {
                    "reason": f"Maximum open positions limit reached ({settings.risk_max_open_positions})",
                    "active_positions": active_positions,
                })
                
        return self._check("max_open_positions", True)

    async def _check_earnings_risk(self, instrument: str) -> dict[str, Any]:
        now_ist = datetime.now(_IST).date()
        if self._earnings_filter.is_near_earnings(instrument, now_ist):
            return self._check("earnings_calendar", False, {
                "reason": "Signal is near corporate earnings result announcement (result day ± 1 session)",
                "check_date": now_ist.isoformat(),
            })
        return self._check("earnings_calendar", True)

    async def _check_correlation_risk(self, instrument: str) -> dict[str, Any]:
        active_positions = [k for k, v in self._positions.items() if v != 0.0 and k != instrument]
        if not active_positions:
            return self._check("correlation", True)
            
        system = getattr(self, "system", None)
        if not system or not hasattr(system, "market_intel") or not hasattr(system.market_intel, "_candle_prices"):
            return self._check("correlation", True)
            
        prices_new = list(system.market_intel._candle_prices.get(instrument, {}).get("minute", []))
        if len(prices_new) < 30:
            return self._check("correlation", True)
            
        import numpy as np
        
        rets_new = np.diff(prices_new) / prices_new[:-1]
        
        for pos_sym in active_positions:
            prices_pos = list(system.market_intel._candle_prices.get(pos_sym, {}).get("minute", []))
            if len(prices_pos) < 30:
                continue
                
            min_len = min(len(prices_new), len(prices_pos))
            aligned_new = np.array(prices_new[-min_len:])
            aligned_pos = np.array(prices_pos[-min_len:])
            
            r_new = np.diff(aligned_new) / aligned_new[:-1]
            r_pos = np.diff(aligned_pos) / aligned_pos[:-1]
            
            if np.std(r_new) == 0 or np.std(r_pos) == 0:
                continue
                
            corr = np.corrcoef(r_new, r_pos)[0, 1]
            if not np.isnan(corr) and corr > 0.7:
                return self._check("correlation", False, {
                    "reason": f"High return correlation ({corr:.2f} > 0.7) with active position {pos_sym}",
                    "correlation": float(corr),
                    "matched_symbol": pos_sym,
                })
                
        return self._check("correlation", True)

    def _track_price(self, event: Event) -> None:
        from collections import deque
        if not hasattr(self, "_price_history"):
            self._price_history: dict[str, deque[float]] = {}
            self._volume_history: dict[str, deque[float]] = {}
        instrument = event.data.get("instrument", "")
        price = event.data.get("last_price") or event.data.get("close")
        volume = event.data.get("volume")
        if price is not None:
            if instrument not in self._price_history:
                self._price_history[instrument] = deque(maxlen=100)
                self._volume_history[instrument] = deque(maxlen=100)
            self._price_history[instrument].append(float(price))
            if volume is not None:
                self._volume_history[instrument].append(float(volume))

    def _maybe_reset_daily_limits(self) -> None:
        """Auto-reset daily limits if the date has changed since last reset."""
        now = datetime.now(UTC)
        if self._last_reset is None or self._last_reset.date() != now.date():
            self._orders_today = 0
            self._order_value_today = 0.0
            self._last_reset = now
            self.logger.info("Daily risk limits auto-reset for %s", now.date())
            
            # Piggyback the KillSwitch daily auto-reset
            from src.risk.kill_switch import KillSwitch
            system = getattr(self, "system", None)
            KillSwitch().daily_auto_reset(system)

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
