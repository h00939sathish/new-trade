import logging
from datetime import datetime
from typing import Any
from src.schemas.events import Event, EventType, SystemEvent

logger = logging.getLogger("risk.kill_switch")

class KillSwitch:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KillSwitch, cls).__new__(cls)
            cls._instance._active = False
            cls._instance._reason = ""
            cls._instance._max_daily_loss = 5000.0  # ₹5,000 max daily loss
            cls._instance._max_drawdown_pct = 0.05  # 5% max drawdown
            cls._instance._initial_capital = None
        return cls._instance

    @property
    def active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    def setup(self, max_daily_loss: float, max_drawdown_pct: float, initial_capital: float) -> None:
        self._max_daily_loss = max_daily_loss
        self._max_drawdown_pct = max_drawdown_pct
        if self._initial_capital is None:
            self._initial_capital = initial_capital

    def reset(self) -> None:
        self._active = False
        self._reason = ""

    async def check_limits(self, current_capital: float, current_pnl: float, peak_capital: float, system=None) -> bool:
        """Check daily PnL and drawdown limits. Trigger kill switch if breached."""
        if self._active:
            return True

        # Check daily loss limit: PnL is realized daily PnL
        if current_pnl < -self._max_daily_loss:
            await self.trigger(f"Daily loss limit breached: {current_pnl} < -{self._max_daily_loss}", system)
            return True

        # Drawdown check: (peak_capital - current_capital) / peak_capital
        if peak_capital > 0:
            drawdown = (peak_capital - current_capital) / peak_capital
            if drawdown > self._max_drawdown_pct:
                await self.trigger(f"Drawdown limit breached: {drawdown * 100:.2f}% > {self._max_drawdown_pct * 100:.2f}%", system)
                return True

        return False

    async def trigger(self, reason: str, system=None) -> None:
        if self._active:
            return
        self._active = True
        self._reason = reason
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

    async def _cleanup_orders_and_positions(self, system) -> None:
        exec_agent = system.execution
        broker = exec_agent._broker

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
                logger.warning("Kill Switch: Market closing position for %s (qty=%d, side=%s)", instrument, qty, side)
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
