import asyncio
import json
import logging

from src.monitoring.metrics import system_metrics
from src.system import TradingSystem

logger = logging.getLogger("monitoring.http_dashboard")


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { font-size: 1.5rem; margin-bottom: 16px; color: #58a6ff; }
  h2 { font-size: 1.1rem; margin-bottom: 8px; color: #8b949e; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card h3 { font-size: 0.9rem; color: #8b949e; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
  .status-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85rem; }
  .label { color: #8b949e; }
  .value { color: #c9d1d9; font-weight: 500; }
  .running { color: #3fb950; }
  .stopped { color: #f85149; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
  .badge-ok { background: #3fb95022; color: #3fb950; border: 1px solid #3fb95044; }
  .badge-err { background: #f8514922; color: #f85149; border: 1px solid #f8514944; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th, td { text-align: left; padding: 6px 4px; border-bottom: 1px solid #21262d; }
  th { color: #8b949e; font-weight: 600; }
  .right { text-align: right; }
  .mt-16 { margin-top: 16px; }
</style>
</head>
<body>
<h1>&#x1F4C8; Trading Dashboard</h1>
<div id="content"></div>
<script>
async function refresh() {
  try {
    const [health, metrics] = await Promise.all([
      fetch('/api/health').then(r => r.json()),
      fetch('/api/metrics').then(r => r.text())
    ]);
    let html = '<div class="grid">';
    for (const [name, status] of Object.entries(health)) {
      const st = status.status || '?';
      const cls = st === 'running' ? 'running' : 'stopped';
      html += '<div class="card"><h3>' + name + '</h3>';
      html += '<div class="status-row"><span class="label">Status</span><span class="value ' + cls + '">' + st + '</span></div>';
      for (const [k, v] of Object.entries(status)) {
        if (['agent','status','event_store','subscribed_types'].includes(k)) continue;
        html += '<div class="status-row"><span class="label">' + k + '</span><span class="value">' + v + '</span></div>';
      }
      html += '</div>';
    }
    html += '</div>';
    html += '<div class="card mt-16"><h3>Prometheus Metrics</h3><pre style="font-size:0.75rem;max-height:300px;overflow:auto;margin-top:8px">' + metrics.slice(0, 2000) + '</pre></div>';
    document.getElementById('content').innerHTML = html;
  } catch (e) {
    document.getElementById('content').innerHTML = '<div class="card"><span class="badge badge-err">Connection Error</span><p style="margin-top:8px">' + e.message + '</p></div>';
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


class HttpDashboard:
    def __init__(self, system: TradingSystem, host: str = "0.0.0.0", port: int = 8081):
        self._system = system
        self._host = host
        self._port = port
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port,
        )
        logger.info("Dashboard listening on http://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await reader.read(4096)
            raw = data.decode("utf-8", errors="replace")
            lines = raw.split("\r\n")
            if not lines:
                writer.close()
                return
            request_line = lines[0]
            parts = request_line.split(" ")
            method = parts[0] if len(parts) > 0 else "GET"
            path = parts[1] if len(parts) > 1 else "/"

            if method == "GET" and path == "/":
                body = HTML.encode()
                ct = "text/html"
                status = "200 OK"
            elif method == "GET" and path == "/api/health":
                health = await self._system.health()
                body = json.dumps(health).encode()
                ct = "application/json"
                status = "200 OK"
            elif method == "GET" and path == "/api/metrics":
                body = system_metrics.prometheus_text().encode()
                ct = "text/plain; charset=utf-8"
                status = "200 OK"
            else:
                body = b"Not Found"
                ct = "text/plain"
                status = "404 Not Found"

            response = (
                f"HTTP/1.1 {status}\r\n"
                f"Content-Type: {ct}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                "\r\n"
            ).encode() + body
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.warning("Dashboard request error: %s", e)
        finally:
            writer.close()
