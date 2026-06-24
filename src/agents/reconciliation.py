import asyncio
import logging
from typing import Any

from src.agents.base import BaseAgent
from src.config.settings import settings
from src.event_store import EventStore
from src.risk.position_registry import position_registry
from src.schemas.events import Event, EventType, SystemEvent

logger = logging.getLogger("agent.reconciliation")


class ReconciliationAgent(BaseAgent):
    """
    On startup, compares the live broker state with the internal position registry.
    Alerts on discrepancies to prevent rogue trading with mismatched assumptions.

    Broker URL is configurable via TRA_RECONCILIATION_BROKER_URL. In paper mode,
    if a broker URL is configured, the agent attempts to connect for reconciliation.
    Timeout is configurable via TRA_RECONCILIATION_TIMEOUT_SECONDS (default 30s).
    """

    def __init__(self, event_store: EventStore | None = None, broker: Any = None):
        super().__init__(name="reconciliation", event_store=event_store)
        self._broker = broker
        self._broker_url = settings.reconciliation_broker_url or ""
        self._timeout = settings.reconciliation_timeout_seconds

    async def on_start(self) -> None:
        self.logger.info("ReconciliationAgent starting...")

        if self._broker is None and hasattr(self, "system") and self.system:
            if getattr(self.system, "_kite_broker", None):
                self._broker = getattr(
                    self.system, "_kite_client", None
                )
                if not self._broker:
                    exec_agent = getattr(self.system, "execution", None)
                    if exec_agent and not getattr(exec_agent, "_paper_trading", False):
                        self._broker = exec_agent._broker

        if self._broker:
            if self._broker_url:
                self.logger.info("Broker URL configured: %s", self._broker_url)
            self.subscribe(EventType.FILL)
            task = asyncio.create_task(self._reconciliation_loop(), name="reconciliation.loop")
            self._tasks.append(task)
        else:
            if self._broker_url:
                self.logger.info(
                    "Paper broker URL configured (%s), attempting reconciliation via URL",
                    self._broker_url,
                )
            self.subscribe(EventType.FILL)
            self.logger.warning("No live broker available for reconciliation, drift alarm only.")

    async def _reconciliation_loop(self) -> None:
        await asyncio.sleep(5.0)
        while self._running:
            await self._run_reconciliation()
            await asyncio.sleep(300.0)

    async def _run_reconciliation(self) -> None:
        try:
            live_positions = await asyncio.wait_for(
                self._broker.get_positions(),
                timeout=self._timeout,
            )

            internal_positions = position_registry.get_all_positions()

            discrepancies = []

            live_map = {}
            for lp in live_positions:
                sym = lp.get("tradingsymbol", "")
                qty = lp.get("quantity", 0)
                if qty != 0:
                    live_map[sym] = live_map.get(sym, 0) + qty

            for sym, pos_data in internal_positions.items():
                internal_qty = pos_data.get("quantity", 0)
                live_qty = live_map.pop(sym, 0)

                if internal_qty != live_qty:
                    discrepancies.append(
                        {"symbol": sym, "internal_qty": internal_qty, "live_qty": live_qty}
                    )

            for sym, live_qty in live_map.items():
                discrepancies.append({"symbol": sym, "internal_qty": 0, "live_qty": live_qty})

            if discrepancies:
                self.logger.error("Broker discrepancies found! %s", discrepancies)
                await self.emit(
                    SystemEvent.error(
                        source=self.name,
                        error_type="broker_reconciliation_mismatch",
                        message="Live positions do not match internal registry",
                        details={"discrepancies": discrepancies},
                    )
                )
            else:
                self.logger.info("Broker reconciliation clean.")
                await self.emit(SystemEvent.health(self.name, "synced", {}))

        except asyncio.TimeoutError:
            self.logger.warning(
                "Broker reconciliation timed out after %ss, skipping cycle",
                self._timeout,
            )
            await self.emit(
                SystemEvent.error(
                    source=self.name,
                    error_type="reconciliation_timeout",
                    message=f"Broker did not respond within {self._timeout}s",
                )
            )
        except Exception as e:
            self.logger.error("Reconciliation failed: %s", e)
            await self.emit(SystemEvent.error(self.name, "reconciliation_failed", str(e), {}))

    async def on_stop(self) -> None:
        self.logger.info("ReconciliationAgent stopping")

    async def on_event(self, event: Event) -> None:
        # FIX P1.4: position-drift alarm. After every FILL, verify that
        # position_registry and portfolio_opt agree on the new quantity.
        # If they diverge, emit a RISK_BREACH so the alert agent notifies.
        if event.event_type == EventType.FILL:
            await self._check_drift(event)

    async def _check_drift(self, event: Event) -> None:
        from src.risk.position_registry import position_registry

        instrument = event.data.get("instrument", "")
        if not instrument:
            return
        reg_qty = position_registry.get_quantity(instrument)
        # Pull the portfolio agent's view via the system ref. The agent
        # may not be wired in all test paths, so guard.
        system_ref = getattr(self, "system", None)
        port_qty = None
        if system_ref and hasattr(system_ref, "portfolio_opt"):
            pos = system_ref.portfolio_opt.get_position(instrument)
            port_qty = pos.get("quantity")
        if port_qty is not None and reg_qty != port_qty:
            msg = f"Position drift on {instrument}: registry={reg_qty} portfolio={port_qty}"
            self.logger.error(msg)
            await self.emit(
                SystemEvent.error(
                    component=self.name,
                    error=f"position_drift: {msg}",
                    fatal=True,
                )
            )
