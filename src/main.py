import asyncio
import logging
import os
import signal

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

system_metrics.start()


async def metrics_http_server(
    health_fn=None,
    host: str = "0.0.0.0",
    port: int = 8080,
):
    handler = await asyncio.start_server(
        lambda r, w: _handle_metrics_request(r, w, health_fn), host, port,
    )
    logger.info("Metrics server listening on %s:%d", host, port)
    async with handler:
        await handler.serve_forever()


async def _handle_metrics_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    health_fn=None,
) -> None:
    data = await reader.read(1024)
    request_line = data.decode("utf-8", errors="ignore").split("\r\n")[0]
    path = request_line.split(" ")[1] if len(request_line.split(" ")) > 1 else "/"

    import json

    if path == "/metrics":
        body_str = system_metrics.prometheus_text()
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
        body = system_metrics.prometheus_text().encode()
        ct = "text/plain; charset=utf-8"
        status = "200 OK"
    elif path == "/":
        body = DASHBOARD_HTML.encode()
        ct = "text/html"
        status = "200 OK"
    else:
        body = b"Not Found"
        ct = "text/plain"
        status = "404 Not Found"
    response = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {ct}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "\r\n"
    ).encode() + body
    writer.write(response)
    await writer.drain()
    writer.close()


async def main():
    system = TradingSystem()
    await system.start()

    watchlist = os.getenv("TRA_WATCHLIST", "RELIANCE,TCS,INFY,HDFCBANK").split(",")
    system.set_watchlist(watchlist)
    logger.info("Watchlist: %s", watchlist)

    dashboard_type = os.getenv("TRA_DASHBOARD_TYPE", "http")
    metrics_port = int(os.getenv("PORT") or os.getenv("TRA_METRICS_PORT", "8080"))

    if dashboard_type == "fastapi":
        from dashboard.server import run_dashboard

        dashboard_port = int(os.getenv("TRA_DASHBOARD_PORT", "8081"))
        dashboard_task = asyncio.create_task(
            asyncio.to_thread(run_dashboard, system, system_metrics, port=dashboard_port),
        )
        logger.info("FastAPI dashboard starting on port %d", dashboard_port)

        metrics_task = None
    else:
        metrics_task = asyncio.create_task(
            metrics_http_server(health_fn=system.health, port=metrics_port),
        )

    use_cli = os.getenv("TRA_DASHBOARD", "1") == "1"
    if use_cli:
        cli_dashboard = CliDashboard(system.health, refresh_interval=2.0)
        cli_task = asyncio.create_task(cli_dashboard.run())
    else:
        cli_dashboard = None
        cli_task = None

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
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        await system.stop()
        logger.info("System shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
