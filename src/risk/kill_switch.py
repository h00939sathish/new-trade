import asyncio
import json
import logging
from pathlib import Path

from src.schemas.events import EventType

logger = logging.getLogger("risk.kill_switch")

_KILL_SWITCH_STATE_PATH = Path("state/kill_switch.state")


class KillSwitch:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._active = False
            cls._instance._reason = ""
            cls._instance._max_daily_loss = 5000.0  # Default fallback
            cls._instance._max_drawdown_pct = 0.05  # 5% max drawdown
            cls._instance._async_lock = None
            cls._instance._initial_capital = None
            cls._instance._triggered_date = None
            cls._instance._auto_reset = False
            cls._instance._restore_state()
        return cls._instance

    def _persist_state(self) -> None:
        try:
            state = {
                "active": self._active,
                "reason": self._reason,
                "triggered_date": (
                    self._triggered_date.isoformat() if self._triggered_date else None
                ),
                "max_daily_loss": self._max_daily_loss,
                "max_drawdown_pct": self._max_drawdown_pct,
                "initial_capital": self._initial_capital,
                "auto_reset": self._auto_reset,
            }
            _KILL_SWITCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _KILL_SWITCH_STATE_PATH.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.error("Failed to persist kill-switch state: %s", e)

    def _restore_state(self) -> None:
        try:
            if _KILL_SWITCH_STATE_PATH.exists():
                state = json.loads(_KILL_SWITCH_STATE_PATH.read_text())
                self._active = state.get("active", False)
                self._reason = state.get("reason", "")
                triggered = state.get("triggered_date")
                if triggered:
                    from datetime import datetime

                    self._triggered_date = datetime.fromisoformat(triggered)
                self._max_daily_loss = state.get("max_daily_loss", self._max_daily_loss)
                self._max_drawdown_pct = state.get("max_drawdown_pct", self._max_drawdown_pct)
                self._initial_capital = state.get("initial_capital", self._initial_capital)
                self._auto_reset = state.get("auto_reset", self._auto_reset)
                if self._active:
                    logger.warning(
                        "Kill Switch RESTORED from persistent state: %s", self._reason
                    )
        except Exception as e:
            logger.error("Failed to restore kill-switch state: %s", e)

    def _get_async_lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    @property
    def active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    def setup(
        self,
        daily_loss_pct: float,
        max_drawdown_pct: float,
        initial_capital: float,
        auto_reset: bool = False,
    ) -> None:
        self._max_drawdown_pct = max_drawdown_pct
        self._auto_reset = auto_reset
        if self._initial_capital is None:
            self._initial_capital = initial_capital
        if self._initial_capital:
            self._max_daily_loss = self._initial_capital * daily_loss_pct

    @classmethod
    def reset_singleton(cls) -> None:
        cls._instance = None

    def reset(self, system=None) -> None:
        self._active = False
        self._reason = ""
        self._triggered_date = None
        self._persist_state()
        if system and hasattr(system, "strategy_gen"):
            system.strategy_gen._running = True
            logger.info("Kill Switch manually reset. Strategy generator re-enabled.")
        else:
            logger.info("Kill Switch manually reset.")

    def daily_auto_reset(self, system=None) -> None:
        """Auto-reset the kill switch at the start of a new trading day."""
        if not self._active or not self._auto_reset or self._triggered_date is None:
            return

        from datetime import UTC, datetime

        now = datetime.now(UTC)
        if self._triggered_date.date() < now.date():
            self._active = False
            self._reason = ""
            self._triggered_date = None
            self._persist_state()
            logger.info("Kill Switch AUTO-RESET for new trading day %s", now.date())
            if system and hasattr(system, "strategy_gen"):
                system.strategy_gen._running = True
                logger.info("Strategy generator re-enabled by auto-reset.")

    async def check_limits(
        self, current_capital: float, current_pnl: float, peak_capital: float, system=None
    ) -> bool:
        """Check daily PnL and drawdown limits. Trigger kill switch if breached."""
        async with self._get_async_lock():
            if self._active:
                return True

            # Check daily loss limit: PnL is realized daily PnL
            if current_pnl < -self._max_daily_loss:
                await self._trigger_impl(
                    f"Daily loss limit breached: {current_pnl} < -{self._max_daily_loss}", system
                )
                return True

            # Drawdown check: (peak_capital - current_capital) / peak_capital
            if peak_capital > 0:
                drawdown = (peak_capital - current_capital) / peak_capital
                if drawdown > self._max_drawdown_pct:
                    await self._trigger_impl(
                        f"Drawdown limit breached: {drawdown * 100:.2f}% > {self._max_drawdown_pct * 100:.2f}%",
                        system,
                    )
                    return True

            return False

    async def _trigger_impl(self, reason: str, system=None) -> None:
        if self._active:
            return
        self._active = True
        self._reason = reason
        from datetime import UTC, datetime

        self._triggered_date = datetime.now(UTC)
        self._persist_state()
        logger.critical("KILL SWITCH TRIGGERED: %s", reason)

        if system:
            try:
                # 1. Disable strategy generator loop
                if hasattr(system, "strategy_gen"):
                    system.strategy_gen._running = False
                    logger.info("Strategy generator disabled by Kill Switch")

                # 2. Emit fatal SYSTEM_ERROR event
                from src.schemas.events import Event, EventMetadata

                err_event = Event(
                    event_type=EventType.SYSTEM_ERROR,
                    stream="system.errors",
                    data={"fatal": True, "reason": reason},
                    metadata=EventMetadata(producer="kill_switch"),
                )
                await system.market_intel.emit(err_event)

                # 3. Cancel all pending orders & close open positions
                await self._cleanup_orders_and_positions(system)
            except Exception as e:
                logger.error("Error during kill switch trigger cleanup: %s", e, exc_info=True)

    async def trigger(self, reason: str, system=None) -> None:
        async with self._get_async_lock():
            await self._trigger_impl(reason, system)

    async def _cleanup_orders_and_positions(self, system) -> None:
        exec_agent = system.execution

        logger.info("Kill Switch: Cancelling all open orders...")
        # Cancel all open/pending orders
        # ExecutionAgent tracks open orders in self._open_orders
        for order_id in list(exec_agent._open_orders.keys()):
            try:
                await exec_agent.cancel_order(order_id)
            except Exception as e:
                logger.error("Kill Switch: Failed to cancel order %s: %s", order_id, e)

        logger.info("Kill Switch: Closing all open positions...")
        portfolio_agent = system.portfolio_opt
        for instrument, pos_data in list(portfolio_agent._positions.items()):
            qty = pos_data.get("quantity", 0)
            if qty != 0:
                side = "sell" if qty > 0 else "buy"
                from src.schemas.events import OrderSide, OrderType, ProductType

                close_side = OrderSide.SELL if qty > 0 else OrderSide.BUY
                logger.warning(
                    "Kill Switch: Market closing position for %s (qty=%d, side=%s)",
                    instrument,
                    qty,
                    side,
                )
                from src.risk.market_impact import MarketImpactModel

                impact_model = MarketImpactModel()
                impact_bps = impact_model.estimate_impact_bps(
                    order_qty=abs(qty),
                    avg_daily_volume=100_000,
                    daily_volatility=0.02,
                )
                logger.warning(
                    "Kill Switch: Estimated market impact for %s (qty=%d): %.2f bps",
                    instrument,
                    abs(qty),
                    impact_bps,
                )
                try:
                    await exec_agent.place_order(
                        instrument=instrument,
                        side=close_side,
                        order_type=OrderType.MARKET,
                        quantity=abs(qty),
                        product=ProductType.MIS,
                    )
                except Exception as e:
                    logger.error("Kill Switch: Failed to close position for %s: %s", instrument, e)
