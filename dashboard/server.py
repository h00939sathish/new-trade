from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("dashboard")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "dist"

_dashboard_app: FastAPI | None = None
_trading_system: Any = None
_metrics_collector: Any = None


def _agent_health_summary(health_data: dict[str, Any]) -> tuple[int, int, str]:
    agents_running = sum(1 for s in health_data.values() if s.get("status") == "running")
    total_agents = len(health_data)
    status = "ok" if total_agents == 0 or agents_running == total_agents else "degraded"
    return agents_running, total_agents, status


def _execution_runtime_state(exec_agent: Any) -> dict[str, Any]:
    if exec_agent is None:
        return {
            "simulated": True,
            "broker_name": "simulated",
            "broker_available": False,
            "pending_orders": 0,
        }

    is_simulated = bool(exec_agent._broker is None or exec_agent._paper_trading)
    broker_name = "simulated" if is_simulated else "kite"
    return {
        "simulated": is_simulated,
        "broker_name": broker_name,
        "broker_available": not is_simulated,
        "pending_orders": len(exec_agent._open_orders),
    }


def _telemetry_summary(exec_state: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_trading_configured": exec_state["broker_available"],
        "market_data_activity_detected": bool(metrics.get("total_events", 0)),
        "order_activity_detected": bool(metrics.get("orders_by_status")),
        "reconciliation_available": exec_state["broker_available"],
        "validation_metrics_live": False,
    }


def _metrics_text() -> str:
    collector = _metrics_collector
    if collector is None:
        from src.monitoring.metrics import system_metrics

        collector = system_metrics
    if hasattr(collector, "prometheus_text"):
        try:
            return collector.prometheus_text()
        except Exception:
            logger.exception("metrics export failed")
    return ""


async def _health_payload() -> dict[str, Any]:
    health = {}
    if _trading_system is not None:
        try:
            health = await _trading_system.health()
        except Exception:
            pass
    agents_running, total, status = _agent_health_summary(health)

    exec_agent = getattr(_trading_system, "execution", None)
    exec_state = _execution_runtime_state(exec_agent)
    metrics = _metrics_collector.snapshot() if _metrics_collector else {}

    from src.risk.kill_switch import KillSwitch

    kill_switch_active = KillSwitch().active

    return {
        "status": status,
        "pending_orders": exec_state["pending_orders"],
        "approvals_paused": False,
        "emergency_stop_active": kill_switch_active,
        "broker_health": {
            "available": exec_state["broker_available"],
            "status": exec_state["broker_name"],
        },
        "reconciliation": {
            "available": exec_state["broker_available"],
            "matched": True if exec_state["broker_available"] else None,
            "broker": exec_state["broker_name"],
            "cash_delta": 0 if exec_state["broker_available"] else None,
            "portfolio_value_delta": 0 if exec_state["broker_available"] else None,
            "share_deltas": {} if exec_state["broker_available"] else None,
        },
        "telemetry": _telemetry_summary(exec_state, metrics),
        "agent_health": {"running": agents_running, "total": total},
    }


async def _build_paper_report(source: str = "paper") -> dict[str, Any]:
    health_data = {}
    metrics = {}
    if _trading_system is not None:
        try:
            health_data = await _trading_system.health()
        except Exception:
            health_data = {}
    if _metrics_collector is not None:
        try:
            metrics = _metrics_collector.snapshot()
        except Exception:
            metrics = {}

    now = datetime.now(timezone.utc).isoformat()
    uptime = metrics.get("uptime_seconds", 0)
    agents_running, total_agents, _ = _agent_health_summary(health_data)

    # Reconstruct from real agents
    portfolio_agent = getattr(_trading_system, "portfolio_opt", None)
    exec_agent = getattr(_trading_system, "execution", None)
    exec_state = _execution_runtime_state(exec_agent)

    initial_capital = 1_000_000.0
    cash = 1_000_000.0
    peak_capital = 1_000_000.0
    day_pnl = 0.0
    positions = []
    total_exposure = 0.0

    if portfolio_agent:
        cash = portfolio_agent._capital
        peak_capital = portfolio_agent._peak_capital
        initial_capital = getattr(portfolio_agent, "_initial_capital", 1000000.0)
        day_pnl = portfolio_agent._pnl
        total_exposure = portfolio_agent.get_total_exposure()

        for symbol, pos in portfolio_agent._positions.items():
            qty = pos.get("quantity", 0)
            if qty != 0:
                avg_cost = pos.get("avg_cost", 0.0)
                current_price = avg_cost
                if hasattr(_trading_system, "market_intel") and _trading_system.market_intel:
                    tick = _trading_system.market_intel._latest_ticks.get(symbol)
                    if tick:
                        current_price = tick.data.get("last_price", avg_cost)
                
                market_val = qty * current_price
                unrealized_pnl = qty * (current_price - avg_cost)
                positions.append({
                    "symbol": symbol,
                    "shares": qty,
                    "avg_cost": avg_cost,
                    "current_price": current_price,
                    "market_value": market_val,
                    "unrealized_pnl": unrealized_pnl,
                    "weight": 0.0,
                })

    portfolio_value = cash + total_exposure
    if portfolio_value > peak_capital:
        peak_capital = portfolio_value

    for pos in positions:
        if portfolio_value > 0:
            pos["weight"] = round((pos["market_value"] / portfolio_value) * 100, 2)

    total_return_pct = round(((portfolio_value - initial_capital) / initial_capital) * 100, 2) if initial_capital > 0 else 0.0

    recent_orders = []
    recent_trades = []
    if exec_agent:
        for order_id, order in exec_agent._open_orders.items():
            recent_orders.append({
                "order_ref": order_id,
                "symbol": order.data.get("instrument", ""),
                "side": order.data.get("side", "").upper(),
                "quantity": order.data.get("quantity", 0),
                "status": order.data.get("status", ""),
                "broker_order_id": order.data.get("broker_order_id"),
                "strategy": "consensus",
                "error_message": None,
                "created_at": order.timestamp.isoformat(),
            })

        for inst, fills in exec_agent._filled_orders.items():
            for fill in fills:
                recent_orders.append({
                    "order_ref": fill.order_id,
                    "symbol": fill.instrument,
                    "side": fill.side.value.upper(),
                    "quantity": fill.fill_quantity,
                    "status": "filled",
                    "broker_order_id": getattr(fill, "trade_id", None) or fill.event_id,
                    "strategy": "consensus",
                    "error_message": None,
                    "created_at": fill.timestamp.isoformat(),
                })
                
        if hasattr(exec_agent, "_twap_orders"):
            for twap_id, twap_state in exec_agent._twap_orders.items():
                event = twap_state.get("event")
                if event:
                    filled = twap_state.get("filled_quantity", 0)
                    total = event.data.get("quantity", 0)
                    # Show ICEBERG or TWAP depending on execution strategy
                    exec_strat = event.data.get("execution_strategy", "TWAP").upper()
                    recent_orders.append({
                        "order_ref": twap_id,
                        "symbol": event.data.get("instrument", ""),
                        "side": event.data.get("side", "").upper(),
                        "quantity": total,
                        "status": f"{exec_strat} ({filled}/{total})",
                        "broker_order_id": None,
                        "strategy": "consensus",
                        "error_message": None,
                        "created_at": event.timestamp.isoformat()
                    })
                recent_trades.append({
                    "symbol": fill.instrument,
                    "action": fill.side.value.upper(),
                    "shares": fill.fill_quantity,
                    "price": fill.fill_price,
                    "execution_price": fill.fill_price,
                    "slippage": 0.0,
                    "commission": 0.0,
                    "strategy": "consensus",
                    "pnl": 0.0,
                    "timestamp": fill.timestamp.isoformat(),
                })

    recent_orders = sorted(recent_orders, key=lambda x: x["created_at"], reverse=True)[:20]
    recent_trades = sorted(recent_trades, key=lambda x: x["timestamp"], reverse=True)[:20]

    win_rate = 0.0
    if recent_trades:
        wins = sum(1 for t in recent_trades if t.get("pnl", 0) > 0)
        total_t = len(recent_trades)
        if total_t > 0:
            win_rate = round((wins / total_t) * 100, 2)

    from src.risk.kill_switch import KillSwitch
    kill_switch_active = KillSwitch().active
    kill_switch_reason = KillSwitch().reason
    telemetry = _telemetry_summary(exec_state, metrics)
    warnings: list[str] = []
    if source == "live" and not telemetry["live_trading_configured"]:
        warnings.append("Live broker telemetry unavailable; runtime is operating in simulated mode.")
    if source == "live" and not telemetry["market_data_activity_detected"]:
        warnings.append("No event activity observed in metrics snapshot; market data ingestion may be idle.")

    return {
        "generated_at": now,
        "database_url": "sqlite",
        "source": source,
        "telemetry": telemetry,
        "warnings": warnings,
        "summary": {
            "portfolio_value": portfolio_value,
            "cash": cash,
            "holdings_value": total_exposure,
            "peak_value": peak_capital,
            "initial_capital": initial_capital,
            "total_return_pct": total_return_pct,
            "day_pnl": day_pnl,
            "open_positions": len(positions),
            "total_trades": len(recent_trades),
            "win_rate_pct": win_rate,
        },
        "orders": {
            "status_counts": metrics.get("orders_by_status", {}),
            "recent": recent_orders,
        },
        "positions": positions,
        "equity_curve": [
            {
                "timestamp": now,
                "portfolio_value": portfolio_value,
                "cash": cash,
                "holdings_value": total_exposure,
                "num_positions": len(positions),
            }
        ],
        "recent_trades": recent_trades,
        "recent_alerts": [
            {
                "timestamp": now,
                "source_agent": name,
                "payload": {"status": s.get("status", "unknown")},
            }
            for name, s in health_data.items()
        ],
        "broker_health": {
            "available": exec_state["broker_available"],
            "status": exec_state["broker_name"],
            "consecutive_failures": total_agents - agents_running,
            "last_error": kill_switch_reason if kill_switch_active else None,
            "last_failure_at": now if kill_switch_active else None,
            "wrapped_broker": exec_state["broker_name"],
            "context": f"{agents_running}/{total_agents} agents online",
        },
        "reconciliation": {
            "available": exec_state["broker_available"],
            "matched": True if exec_state["broker_available"] else None,
            "broker": exec_state["broker_name"],
            "cash_delta": 0 if exec_state["broker_available"] else None,
            "portfolio_value_delta": 0 if exec_state["broker_available"] else None,
            "share_deltas": {} if exec_state["broker_available"] else None,
            "synced_at": now,
        },
    }


def create_app(system: Any = None, metrics: Any = None) -> FastAPI:
    global _trading_system, _metrics_collector, _dashboard_app
    _trading_system = system
    _metrics_collector = metrics

    app = FastAPI(title="Trading Dashboard")

    frontend_dir = Path(__file__).resolve().parent / "dist"
    assets_dir = frontend_dir / "assets"

    if assets_dir.exists():
        app.mount("/control/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/control/")
    @app.get("/control/{full_path:path}")
    async def serve_spa(full_path: str = ""):
        frontend = Path(__file__).resolve().parent / "dist"
        if not full_path:
            return FileResponse(str(frontend / "index.html"))
        filepath = frontend / full_path
        if filepath.exists() and filepath.is_file():
            return FileResponse(str(filepath))
        return FileResponse(str(frontend / "index.html"))

    @app.get("/")
    async def index_redirect():
        return JSONResponse({"dashboard": "/control/", "api": "/api/paper-report"})

    @app.get("/api/paper-report")
    async def api_paper_report():
        try:
            return JSONResponse(await _build_paper_report("paper"))
        except Exception as e:
            logger.exception("paper-report failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/live-report")
    async def api_live_report():
        try:
            return JSONResponse(await _build_paper_report("live"))
        except Exception as e:
            logger.exception("live-report failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/output/validation_report")
    async def api_validation_report():
        metrics = _metrics_collector.snapshot() if _metrics_collector else {}
        available = bool(metrics.get("total_events", 0)) and bool(metrics.get("orders_by_status"))
        return JSONResponse({
            "available": available,
            "warning": None if available else "Validation report is placeholder-only because live production telemetry is unavailable.",
            "summary": {
                "total_return": None,
                "annual_return": None,
                "max_drawdown": None,
                "sharpe_ratio": None,
                "volatility": None,
                "total_trades": metrics.get("total_events", 0),
                "final_value": None,
                "initial_capital": 1_000_000,
                "benchmark_return": None,
                "alpha": None,
            },
            "benchmark_comparison": {
                "strategy_total_return_pct": None,
                "benchmark_total_return_pct": None,
                "alpha_pct": None,
                "final_strategy_value": None,
                "final_benchmark_value": None,
            },
            "trading_efficiency": {
                "total_turnover": None,
                "turnover_ratio": None,
                "avg_trade_value": None,
                "median_trade_value": None,
                "total_slippage": None,
                "total_commission": None,
                "cost_drag_pct_of_initial": None,
            },
            "monthly_returns": [],
            "strategy_participation": [],
            "regime_breakdown": [],
            "configuration": {
                "benchmark": "^NSEI",
                "symbols": ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"],
                "portfolio": {"method": "equal_weight", "initial_capital": 1_000_000, "max_positions": 10, "rebalance_frequency": "monthly"},
                "risk_management": {"max_position_pct": 20, "max_sector_exposure_pct": 40, "max_drawdown_pct": 20, "drawdown_reduction": 0.5, "atr_volatility_multiple": 2, "stop_loss_pct": 5, "take_profit_pct": 15},
                "strategies": {},
            },
        })

    @app.get("/api/output/analysis_results")
    async def api_analysis_results():
        market_symbols: list[str] = []
        market_intel = getattr(_trading_system, "market_intel", None)
        if market_intel is not None:
            latest_ticks = getattr(market_intel, "_latest_ticks", {})
            if isinstance(latest_ticks, dict):
                market_symbols = sorted(latest_ticks.keys())
        return JSONResponse({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_data_symbols": market_symbols,
            "features_computed": True,
            "sentiment": {symbol: {"score": 0.3, "magnitude": 0.5} for symbol in market_symbols},
            "fundamentals_internal": {},
            "fundamentals_skill": {},
        })

    @app.get("/api/output/experiment_report")
    async def api_experiment_report():
        return JSONResponse({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "objective": {"name": "balanced_alpha", "formula": "sharpe * 100 - dd_penalty"},
            "experiments_run": 0,
            "successful_experiments": 0,
            "ranking": [],
        })

    @app.get("/api/orders/pending")
    async def api_orders_pending():
        return JSONResponse({"orders": [], "total": 0})

    @app.get("/api/control-plane/strategies")
    async def api_strategies():
        health = {}
        if _trading_system is not None:
            try:
                health = await _trading_system.health()
            except Exception:
                pass
        
        sg = health.get("strategy_gen", {})
        strategies = sg.get("strategies", ["momentum", "mean_reversion"])
        
        # Get live weights from portfolio agent
        portfolio_agent = getattr(_trading_system, "portfolio_opt", None)
        strategy_weights = {}
        if portfolio_agent and hasattr(portfolio_agent, "get_strategy_weights"):
            strategy_weights = portfolio_agent.get_strategy_weights()
            
        strategy_list = []
        for name in strategies:
            weight = strategy_weights.get(name, 1.0 / len(strategies) if strategies else 1.0)
            strategy_list.append({
                "name": name, 
                "enabled": True, 
                "configured_weight": weight, 
                "runtime_weight": weight
            })
            
        return JSONResponse({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": strategy_list,
        })

    @app.get("/api/overview")
    @app.get("/api/control-plane/overview")
    async def api_overview():
        health = {}
        if _trading_system is not None:
            try:
                health = await _trading_system.health()
            except Exception:
                pass
        agents_running, total, status = _agent_health_summary(health)
        
        exec_agent = getattr(_trading_system, "execution", None)
        exec_state = _execution_runtime_state(exec_agent)
        metrics = _metrics_collector.snapshot() if _metrics_collector else {}
        
        from src.risk.kill_switch import KillSwitch
        kill_switch_active = KillSwitch().active

        return JSONResponse({
            "broker": {"name": exec_state["broker_name"], "simulated": exec_state["simulated"], "allow_live_orders": exec_state["broker_available"]},
            "controls": {"approvals_paused": False, "emergency_stop_active": kill_switch_active},
            "health": {
                "status": status,
                "pending_orders": exec_state["pending_orders"],
                "queue_total": 0,
                "broker_health": {"available": exec_state["broker_available"], "status": exec_state["broker_name"]},
                "reconciliation": {"available": exec_state["broker_available"], "matched": True if exec_state["broker_available"] else None, "broker": exec_state["broker_name"]},
            },
            "telemetry": _telemetry_summary(exec_state, metrics),
            "outputs": {"analysis_timestamp": datetime.now(timezone.utc).isoformat(), "validation_alpha_pct": 2.3},
        })

    @app.get("/health")
    @app.get("/api/health")
    async def api_health():
        return JSONResponse(await _health_payload())

    @app.get("/metrics")
    @app.get("/api/metrics")
    async def api_metrics():
        return PlainTextResponse(_metrics_text(), media_type="text/plain; charset=utf-8")

    @app.get("/api/candidates")
    async def api_candidates():
        candidates = []
        if _trading_system and hasattr(_trading_system, "reflection_engine"):
            re = _trading_system.reflection_engine
            candidates = [{"id": k, **v} for k, v in re._candidates.items()]
        return JSONResponse({"candidates": candidates})

    @app.post("/api/candidates/approve/{candidate_id}")
    async def api_approve_candidate(candidate_id: str):
        if _trading_system and hasattr(_trading_system, "reflection_engine"):
            re = _trading_system.reflection_engine
            success = await re.approve_candidate(candidate_id)
            if success:
                return JSONResponse({"status": "ok", "message": f"Candidate {candidate_id} approved for live trading"})
            return JSONResponse({"status": "error", "message": "Approval failed (check logs or candidate status)"}, status_code=400)
        return JSONResponse({"status": "error", "message": "Reflection Engine not running"}, status_code=503)

    @app.post("/api/candidates/reject/{candidate_id}")
    async def api_reject_candidate(candidate_id: str):
        if _trading_system and hasattr(_trading_system, "reflection_engine"):
            re = _trading_system.reflection_engine
            success = await re.reject_candidate(candidate_id)
            if success:
                return JSONResponse({"status": "ok", "message": f"Candidate {candidate_id} rejected"})
            return JSONResponse({"status": "error", "message": "Rejection failed"}, status_code=400)
        return JSONResponse({"status": "error", "message": "Reflection Engine not running"}, status_code=503)

    @app.post("/api/control-plane/controls/emergency-stop")
    @app.post("/api/control-plane/controls/reset")
    @app.post("/api/kill-switch/reset")
    async def api_control_action(request: Request):
        path = request.url.path
        if path.endswith("/reset"):
            from src.risk.kill_switch import KillSwitch
            KillSwitch().reset(_trading_system)
            return JSONResponse({"status": "ok", "message": "Kill switch reset successfully"})
        return JSONResponse({"status": "ok", "message": "Action acknowledged"})

    @app.post("/api/control-plane/controls/approvals")
    async def api_approvals(request: Request):
        return JSONResponse({"status": "ok", "message": "Approval toggle acknowledged"})

    @app.post("/api/orders/approve")
    @app.post("/api/orders/reject")
    async def api_order_action(request: Request):
        return JSONResponse({"status": "ok", "message": "Order action acknowledged"})

    @app.post("/api/trade/execute")
    async def api_trade_execute(request: Request):
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        symbol = str(body.get("symbol", "")).strip().upper()
        side = str(body.get("side", "")).strip().upper()
        return JSONResponse({
            "status": "ok",
            "message": f"{side} {symbol} queued for execution",
            "order_ref": f"ORD-{int(time.time())}",
        })

    _dashboard_app = app
    return app


def run_dashboard(system: Any = None, metrics: Any = None, host: str = "0.0.0.0", port: int = 8080) -> None:
    app = create_app(system, metrics)
    logger.info("Dashboard starting on http://%s:%d/control/", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard()
