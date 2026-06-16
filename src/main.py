import asyncio
import logging
import os
import signal
from pathlib import Path

from src.config.settings import settings
from src.monitoring.dashboard import CliDashboard
from src.monitoring.http_dashboard import HTML as DASHBOARD_HTML
from src.monitoring.metrics import system_metrics
from src.system import TradingSystem

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

_auth_token = os.environ.get("TRA_HTTP_AUTH_TOKEN", "").strip()
if not _auth_token:
    if settings.live_trading_enabled:
        raise RuntimeError(
            "CRITICAL: TRA_HTTP_AUTH_TOKEN is empty but live trading is enabled. "
            "Set the env var to a random 32+ byte string (e.g. `openssl rand -hex 32`)."
            "Refusing to start with exposed kill-switch and control endpoints."
        )
    logger.warning(
        "TRA_HTTP_AUTH_TOKEN is empty; HTTP control endpoints are UNAUTHENTICATED. "
        "Set the env var to a random 32+ byte string (e.g. `openssl rand -hex 32`)."
    )

system_metrics.start()


async def metrics_http_server(
    system=None,
    health_fn=None,
    host: str = "0.0.0.0",
    port: int = 8080,
):
    handler = await asyncio.start_server(
        lambda r, w: _handle_metrics_request(r, w, health_fn, system),
        host,
        port,
    )
    logger.info("Metrics server listening on %s:%d", host, port)
    async with handler:
        await handler.serve_forever()


async def _handle_metrics_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    health_fn=None,
    system=None,
) -> None:
    data = await reader.read(4096)
    request_text = data.decode("utf-8", errors="ignore")
    request_line = request_text.split("\r\n")[0]
    path = request_line.split(" ")[1] if len(request_line.split(" ")) > 1 else "/"

    # Basic bearer token authentication
    auth_token = os.environ.get("TRA_HTTP_AUTH_TOKEN", "")
    if auth_token:
        auth_header = ""
        for line in request_text.split("\r\n"):
            if line.lower().startswith("authorization:"):
                auth_header = line.split(":", 1)[1].strip()
                break
        expected = f"Bearer {auth_token}"
        if auth_header != expected:
            body = b"Unauthorized"
            response = (
                "HTTP/1.1 401 Unauthorized\r\n"
                "Content-Type: text/plain\r\n"
                f"Content-Length: {len(body)}\r\n"
                "\r\n"
            ).encode() + body
            writer.write(response)
            await writer.drain()
            writer.close()
            return

    import json

    if path == "/metrics":
        body_str = system_metrics.prometheus_text(system)
        body = body_str.encode()
        ct = "text/plain; charset=utf-8"
        status = "200 OK"
    elif path == "/health":
        if health_fn:
            health_data = await health_fn()
            body = json.dumps(health_data, default=str).encode()
        else:
            body = b'{"status": "ok"}'
        ct = "application/json"
        status = "200 OK"
    elif path == "/api/health":
        health_data = await health_fn() if health_fn else {"status": "ok"}
        body = json.dumps(health_data, default=str).encode()
        ct = "application/json"
        status = "200 OK"
    elif path == "/api/metrics":
        body = system_metrics.prometheus_text(system).encode()
        ct = "text/plain; charset=utf-8"
        status = "200 OK"
    elif path == "/":
        body = DASHBOARD_HTML.encode()
        ct = "text/html"
        status = "200 OK"
    elif path == "/api/kill-switch/reset" and request_line.startswith("POST"):
        from src.risk.kill_switch import KillSwitch

        KillSwitch().reset(system=system)
        body = b'{"status": "ok", "message": "Kill switch reset"}'
        ct = "application/json"
        status = "200 OK"
    else:
        body = b"Not Found"
        ct = "text/plain"
        status = "404 Not Found"
    response = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {ct}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Access-Control-Allow-Origin: http://localhost\r\n"
        "\r\n"
    ).encode() + body
    writer.write(response)
    await writer.drain()
    writer.close()


async def main():
    system = TradingSystem()
    watchlist = os.getenv("TRA_WATCHLIST", "RELIANCE,TCS,INFY,HDFCBANK").split(",")
    system.set_watchlist(watchlist)
    logger.info("Watchlist: %s", watchlist)

    # Persist metrics counters to SQLite so they survive restarts.
    # The store is opt-in (see MetricsCollector.attach_store); we wire
    # it up here, then re-call start() to schedule the flush task
    # (the module-level start() at line 26 short-circuited because
    # no store was attached at import time).
    from src.monitoring.metrics_store import MetricsStore

    _metrics_db_path = Path(
        os.getenv("TRA_METRICS_DB", "state/metrics.db")
    )
    system_metrics.attach_store(MetricsStore(_metrics_db_path))
    _loaded = await system_metrics.load_from_store()
    if _loaded:
        logger.info(
            "Restored %d metric series from %s",
            sum(_loaded.values()),
            _metrics_db_path,
        )
    system_metrics.start()
    if settings.live_trading_enabled:
        if not settings.kite_api_key or not settings.kite_access_token:
            raise RuntimeError(
                "CRITICAL: TRA_LIVE_TRADING_ENABLED is True but Kite credentials (TRA_KITE_API_KEY/TRA_KITE_ACCESS_TOKEN) are missing! "
                "Refusing to start in live mode without valid broker credentials."
            )
        logger.warning("!!! WARNING: SYSTEM STARTING IN LIVE TRADING MODE !!!")

    await system.start()

    dashboard_type = os.getenv("TRA_DASHBOARD_TYPE", "http")
    metrics_port = int(os.getenv("PORT") or os.getenv("TRA_METRICS_PORT", "8080"))

    if dashboard_type == "fastapi":
        from dashboard.server import run_dashboard

        dashboard_port = int(os.getenv("PORT") or os.getenv("TRA_DASHBOARD_PORT", "8081"))
        dashboard_task = asyncio.create_task(
            asyncio.to_thread(
                run_dashboard, system, system_metrics, host="0.0.0.0", port=dashboard_port
            ),
        )
        logger.info("FastAPI dashboard starting on port %d", dashboard_port)

        metrics_task = None
    else:
        metrics_task = asyncio.create_task(
            metrics_http_server(system=system, health_fn=system.health, port=metrics_port),
        )

    use_cli = os.getenv("TRA_DASHBOARD", "1") == "1"
    if use_cli:
        cli_dashboard = CliDashboard(system.health, refresh_interval=2.0)
        cli_task = asyncio.create_task(cli_dashboard.run())
    else:
        cli_dashboard = None
        cli_task = None

    # FIX P1.3: paper burn-in reconciliation runs by default in paper mode.
    # Set TRA_BURNIN=0 to disable, TRA_BURNIN_RECONCILIATION_SECONDS to override
    # the interval (default 300s = 5 minutes per three_stage_roadmap.md P1.3).
    # The 1800s default from before was too sparse to catch drift quickly.
    burnin_task = None
    paper_mode = getattr(system.execution, "_paper_trading", True)
    burnin_enabled = os.getenv("TRA_BURNIN", "1" if paper_mode else "0") == "1"
    if burnin_enabled:
        from src.monitoring.burnin import run_paper_reconciliation_loop

        reconciliation_path = Path(
            os.getenv("TRA_BURNIN_RECONCILIATION_PATH", "state/burnin/reconciliation.jsonl"),
        )
        reconciliation_interval = float(
            os.getenv("TRA_BURNIN_RECONCILIATION_SECONDS", "300"),
        )
        burnin_task = asyncio.create_task(
            run_paper_reconciliation_loop(
                system,
                reconciliation_path,
                interval_seconds=reconciliation_interval,
            ),
        )
        logger.info(
            "Paper burn-in reconciliation enabled (interval=%.0fs, paper=%s)",
            reconciliation_interval,
            paper_mode,
        )

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    for sig_id in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_id, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        all_tasks = []
        if dashboard_type == "fastapi":
            all_tasks.append(dashboard_task)
        else:
            if metrics_task:
                metrics_task.cancel()
                all_tasks.append(metrics_task)
        if cli_task:
            cli_task.cancel()
            all_tasks.append(cli_task)
        if burnin_task:
            burnin_task.cancel()
            all_tasks.append(burnin_task)
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        await system.stop()
        # Final flush of any pending metric writes to the store.
        try:
            await system_metrics.stop()
        except Exception as exc:  # pragma: no cover - logged not raised
            logger.warning("Metrics flush on shutdown failed: %s", exc)
        logger.info("System shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
