import logging

from src.schemas.events import RiskCheckEvent

logger = logging.getLogger("risk.reconciliation")

async def reconcile_positions(system) -> None:
    """Compare broker positions against local portfolio agent tracked positions.
    
    Broker is the source of truth. If a mismatch is found, we log a RISK_BREACH event,
    update the local portfolio agent's positions, and emit updates.
    """
    exec_agent = getattr(system, "execution", None)
    portfolio_agent = getattr(system, "portfolio_opt", None)
    if not exec_agent or not portfolio_agent:
        return

    broker = exec_agent._broker
    if not broker:
        # Paper trading or no broker connected: skip reconciliation
        return

    try:
        broker_positions_raw = await broker.get_positions()
        # Handle dict or list format returned by get_positions()
        if isinstance(broker_positions_raw, dict):
            net_positions = broker_positions_raw.get("net", [])
        else:
            net_positions = broker_positions_raw

        broker_positions = {}
        for pos in net_positions:
            symbol = pos.get("tradingsymbol", "")
            qty = int(pos.get("quantity", 0))
            if symbol and qty != 0:
                broker_positions[symbol] = qty
    except Exception as e:
        logger.error("Reconciliation: Failed to get broker positions: %s", e)
        return

    # Local positions
    local_positions = {}
    for symbol, pos_data in portfolio_agent._positions.items():
        qty = int(pos_data.get("quantity", 0))
        if qty != 0:
            local_positions[symbol] = qty

    # Check for mismatches
    all_symbols = set(broker_positions.keys()).union(set(local_positions.keys()))
    mismatches = {}
    for symbol in all_symbols:
        b_qty = broker_positions.get(symbol, 0)
        l_qty = local_positions.get(symbol, 0)
        if b_qty != l_qty:
            mismatches[symbol] = {"broker": b_qty, "local": l_qty}

    if mismatches:
        logger.warning("Reconciliation: Position mismatch detected! %s", mismatches)
        for symbol, data in mismatches.items():
            b_qty = data["broker"]
            l_qty = data["local"]

            # Emit Risk Breach Event
            breach_event = RiskCheckEvent.create(
                check_name="position_reconciliation",
                passed=False,
                instrument=symbol,
                details={
                    "broker_qty": b_qty,
                    "local_qty": l_qty,
                    "mismatch": b_qty - l_qty
                },
                producer="reconciliation"
            )
            await portfolio_agent.emit(breach_event)

            # Reconcile local state: update local to match broker
            if symbol not in portfolio_agent._positions:
                portfolio_agent._positions[symbol] = {
                    "quantity": 0,
                    "avg_cost": 0.0,
                    "total_bought": 0,
                    "total_sold": 0,
                }
            portfolio_agent._positions[symbol]["quantity"] = b_qty
            if b_qty == 0:
                portfolio_agent._positions[symbol]["avg_cost"] = 0.0

            # Emit portfolio update to sync with execution and other agents
            await portfolio_agent._emit_portfolio_update(symbol, "buy" if b_qty > 0 else "sell")
    else:
        logger.info("Reconciliation: Local positions match broker positions successfully.")
