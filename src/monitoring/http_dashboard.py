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
  :root {
    --navy: #0a0e17;
    --navy-light: #111827;
    --navy-lighter: #1e293b;
    --teal: #14b8a6;
    --teal-dim: #0d9488;
    --green: #22c55e;
    --red: #ef4444;
    --amber: #f59e0b;
    --slate: #64748b;
    --slate-light: #94a3b8;
    --text: #e2e8f0;
    --text-dim: #64748b;
    --radius: 6px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Cascadia Code', 'Segoe UI', system-ui, monospace;
    background: var(--navy); color: var(--text); padding: 0; min-height: 100vh;
  }

  /* Header */
  .header {
    background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
    border-bottom: 1px solid var(--navy-lighter);
    padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
  }
  .header-left { display: flex; align-items: center; gap: 16px; }
  .header-logo {
    width: 36px; height: 36px; border-radius: var(--radius);
    background: linear-gradient(135deg, var(--teal), var(--teal-dim));
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 700; color: #fff; flex-shrink: 0;
  }
  .header-title { font-size: 1.15rem; font-weight: 600; letter-spacing: -0.3px; }
  .header-title span { color: var(--teal); }
  .header-right { display: flex; align-items: center; gap: 20px; font-size: 0.8rem; color: var(--slate-light); }
  .header-stat { display: flex; align-items: center; gap: 6px; }
  .header-stat .val { color: var(--text); font-weight: 500; }

  .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .status-dot.ok { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .status-dot.err { background: var(--red); box-shadow: 0 0 6px var(--red); }
  .status-dot.warn { background: var(--amber); box-shadow: 0 0 6px var(--amber); }

  /* Layout */
  .container { max-width: 1440px; margin: 0 auto; padding: 20px 24px; }

  .section-title {
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px;
    color: var(--text-dim); margin-bottom: 12px; font-weight: 600;
  }

  /* Stats Bar */
  .stats-bar {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px; margin-bottom: 24px;
  }
  .stat-card {
    background: var(--navy-light); border: 1px solid var(--navy-lighter);
    border-radius: var(--radius); padding: 14px 16px; transition: border-color .2s;
  }
  .stat-card:hover { border-color: var(--teal); }
  .stat-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); }
  .stat-value { font-size: 1.5rem; font-weight: 700; margin-top: 4px; line-height: 1.2; }
  .stat-value.green { color: var(--green); }
  .stat-value.teal { color: var(--teal); }
  .stat-value.amber { color: var(--amber); }
  .stat-value.red { color: var(--red); }
  .stat-sub { font-size: 0.7rem; color: var(--text-dim); margin-top: 2px; }

  /* Agent Grid */
  .agent-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 12px; margin-bottom: 24px;
  }
  .agent-card {
    background: var(--navy-light); border: 1px solid var(--navy-lighter);
    border-radius: var(--radius); padding: 16px; transition: border-color .2s, box-shadow .2s;
  }
  .agent-card:hover { border-color: #334155; }
  .agent-card.running { border-left: 3px solid var(--green); }
  .agent-card.stopped { border-left: 3px solid var(--red); }
  .agent-card.error { border-left: 3px solid var(--amber); }
  .agent-header {
    display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;
  }
  .agent-name { font-size: 0.85rem; font-weight: 600; }
  .agent-status {
    display: flex; align-items: center; gap: 6px;
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px;
    padding: 3px 10px; border-radius: 10px; font-weight: 600;
  }
  .agent-status.running { color: var(--green); background: #22c55e15; }
  .agent-status.stopped { color: var(--red); background: #ef444415; }
  .agent-status.error { color: var(--amber); background: #f59e0b15; }
  .agent-status.created,
  .agent-status.starting,
  .agent-status.stopping { color: var(--slate-light); background: #64748b15; }
  .agent-details { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; }
  .agent-detail { display: flex; justify-content: space-between; font-size: 0.78rem; padding: 3px 0; border-bottom: 1px solid #1e293b40; }
  .agent-detail:last-child { border-bottom: none; }
  .agent-detail .lbl { color: var(--text-dim); }
  .agent-detail .val { color: var(--text); font-weight: 500; }

  /* Prometheus Section */
  .metrics-section { margin-bottom: 24px; }
  .metrics-toggle {
    background: var(--navy-light); border: 1px solid var(--navy-lighter);
    border-radius: var(--radius); padding: 12px 16px; cursor: pointer;
    display: flex; align-items: center; justify-content: space-between;
    font-size: 0.8rem; color: var(--text); transition: border-color .2s;
    width: 100%; text-align: left;
  }
  .metrics-toggle:hover { border-color: #334155; }
  .metrics-toggle .arrow { transition: transform .2s; font-size: 0.7rem; color: var(--text-dim); }
  .metrics-toggle.open .arrow { transform: rotate(90deg); }
  .metrics-body {
    background: var(--navy-light); border: 1px solid var(--navy-lighter); border-top: none;
    border-radius: 0 0 var(--radius) var(--radius); padding: 0 16px; max-height: 0;
    overflow: hidden; transition: max-height .3s, padding .3s;
  }
  .metrics-body.open { max-height: 400px; padding: 16px; }
  .metrics-body pre {
    font-size: 0.72rem; line-height: 1.5; color: var(--slate-light);
    max-height: 320px; overflow: auto;
  }
  .metrics-body pre::-webkit-scrollbar { width: 4px; }
  .metrics-body pre::-webkit-scrollbar-thumb { background: var(--navy-lighter); border-radius: 2px; }

  /* Error/Warning states */
  .error-state {
    background: var(--navy-light); border: 1px solid #ef444430;
    border-radius: var(--radius); padding: 24px; text-align: center;
  }
  .error-state .icon { font-size: 2rem; margin-bottom: 8px; }
  .error-state .msg { color: var(--red); font-size: 0.85rem; }

  /* Footer */
  .footer {
    text-align: center; padding: 20px; font-size: 0.72rem; color: var(--text-dim);
    border-top: 1px solid var(--navy-lighter); margin-top: 12px;
  }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: var(--navy); }
  ::-webkit-scrollbar-thumb { background: var(--navy-lighter); border-radius: 3px; }

  /* Tables */
  table { width: 100%; border-collapse: collapse; margin-bottom: 0; font-size: 0.8rem; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--navy-lighter); }
  th { color: var(--text-dim); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; }
  tr:hover td { background: var(--navy-lighter); }
  .tbl-container { background: var(--navy-light); border: 1px solid var(--navy-lighter); border-radius: var(--radius); overflow-x: auto; margin-bottom: 24px; }

  @media (max-width: 640px) {
    .header { padding: 12px 16px; }
    .container { padding: 12px 16px; }
    .agent-grid { grid-template-columns: 1fr; }
    .stats-bar { grid-template-columns: repeat(2, 1fr); }
    .stat-value { font-size: 1.2rem; }
    .agent-details { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <div class="header-logo">&#8747;</div>
    <div class="header-title"><span>Trade</span> System</div>
  </div>
  <div class="header-right" id="headerRight">
    <div class="header-stat"><span class="status-dot" id="systemDot"></span><span id="systemStatus">Loading...</span></div>
    <div class="header-stat">Uptime <span class="val" id="uptime">-</span></div>
    <div class="header-stat">Updated <span class="val" id="lastRefresh">-</span></div>
  </div>
</div>

<div class="container">
  <div class="stats-bar" id="statsBar">
    <div class="stat-card"><div class="stat-label">Events Total</div><div class="stat-value teal" id="statEvents">-</div></div>
    <div class="stat-card"><div class="stat-label">Event Rate</div><div class="stat-value" id="statRate" style="color:var(--text)">-</div><div class="stat-sub">events/sec</div></div>
    <div class="stat-card"><div class="stat-label">Avg Latency</div><div class="stat-value" id="statLatency" style="color:var(--text)">-</div><div class="stat-sub">ms</div></div>
    <div class="stat-card"><div class="stat-label">Signals</div><div class="stat-value amber" id="statSignals">-</div></div>
    <div class="stat-card"><div class="stat-label">Errors</div><div class="stat-value red" id="statErrors">-</div></div>
  </div>

  <div class="section-title">Agent Status</div>
  <div class="agent-grid" id="agentGrid"></div>

  <div class="section-title">Active Executions</div>
  <div id="execGrid"><div style="color:var(--text-dim);margin-bottom:24px;font-size:0.8rem">No active orders</div></div>

  <div class="section-title">Slippage Analytics</div>
  <div id="slippageGrid"><div style="color:var(--text-dim);margin-bottom:24px;font-size:0.8rem">No fill data</div></div>

  <div class="metrics-section">
    <button class="metrics-toggle" id="metricsToggle" onclick="toggleMetrics()">
      <span>&#x2699; Prometheus Metrics</span>
      <span class="arrow">&#x25B6;</span>
    </button>
    <div class="metrics-body" id="metricsBody">
      <pre id="metricsPre">Loading...</pre>
    </div>
  </div>
</div>

<div class="footer">Trading System v1 &middot; Press Ctrl+C in terminal to stop</div>

<script>
function fmtTime(ts) {
  return ts.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtUptime(s) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (d > 0) return d + 'd ' + h + 'h ' + m + 'm';
  if (h > 0) return h + 'h ' + m + 'm ' + sec + 's';
  if (m > 0) return m + 'm ' + sec + 's';
  return sec + 's';
}

function esc(s) {
  if (s === null || s === undefined) return '-';
  const t = typeof s;
  if (t === 'boolean') return s ? 'true' : 'false';
  return String(s);
}

function agentDetailKey(k) {
  return k
    .replace(/_/g, ' ')
    .replace(/\\b\\w/g, c => c.toUpperCase());
}

function runningCount(health) {
  let n = 0;
  for (const st of Object.values(health)) {
    if (st.status === 'running') n++;
  }
  return n;
}

function toggleMetrics() {
  const btn = document.getElementById('metricsToggle');
  const body = document.getElementById('metricsBody');
  const open = body.classList.toggle('open');
  btn.classList.toggle('open', open);
}

async function refresh() {
  try {
    const [health, metricsJson, metricsText] = await Promise.all([
      fetch('/api/health').then(r => r.json()),
      fetch('/api/metrics/json').then(r => r.json()),
      fetch('/api/metrics').then(r => r.text())
    ]);

    const now = new Date();
    document.getElementById('lastRefresh').textContent = fmtTime(now);

    /* System status dot */
    const allOk = Object.values(health).every(s => s.status === 'running');
    const dot = document.getElementById('systemDot');
    const statusLabel = document.getElementById('systemStatus');
    if (allOk) {
      dot.className = 'status-dot ok';
      statusLabel.textContent = 'All Systems Nominal';
    } else {
      dot.className = 'status-dot err';
      statusLabel.textContent = 'Degraded';
    }

    /* Uptime */
    if (metricsJson.uptime_seconds) {
      document.getElementById('uptime').textContent = fmtUptime(metricsJson.uptime_seconds);
    }

    /* Stats bar */
    document.getElementById('statEvents').textContent = (metricsJson.total_events || 0).toLocaleString();
    document.getElementById('statRate').textContent = (metricsJson.event_rate || 0).toFixed(1);
    document.getElementById('statLatency').textContent = (metricsJson.avg_latency_ms || 0).toFixed(1);

    const signals = metricsJson.signals_by_strategy || {};
    const totalSignals = Object.values(signals).reduce((a, b) => a + b, 0);
    document.getElementById('statSignals').textContent = totalSignals;

    const errors = metricsJson.errors_by_component || {};
    const totalErrors = Object.values(errors).reduce((a, b) => a + b, 0);
    document.getElementById('statErrors').textContent = totalErrors;

    /* Agent cards */
    const agents = Object.entries(health);
    const totalAgents = agents.length;
    const running = runningCount(health);
    let gridHtml = '';
    for (const [name, st] of agents) {
      const status = st.status || 'unknown';
      const statusClass = status === 'running' ? 'running' : (status === 'error' ? 'error' : 'stopped');
      gridHtml += '<div class="agent-card ' + statusClass + '">';
      gridHtml += '<div class="agent-header">';
      gridHtml += '<div class="agent-name">' + name + '</div>';
      gridHtml += '<div class="agent-status ' + statusClass + '"><span class="status-dot ' + (status === 'running' ? 'ok' : 'err') + '"></span>' + status + '</div>';
      gridHtml += '</div>';
      gridHtml += '<div class="agent-details">';
      for (const [k, v] of Object.entries(st)) {
        if (['agent', 'status', 'event_store', 'subscribed_types'].includes(k)) continue;
        let val = esc(v);
        const valClass = k === 'paper_trading' && v ? 'teal' : '';
        gridHtml += '<div class="agent-detail"><span class="lbl">' + agentDetailKey(k) + '</span><span class="val' + (valClass ? ' ' + valClass : '') + '">' + val + '</span></div>';
      }
      gridHtml += '</div></div>';
    }
    document.getElementById('agentGrid').innerHTML = gridHtml;

    /* Metrics text */
    document.getElementById('metricsPre').textContent = metricsText;

    /* Executions & Slippage */
    const execJson = await fetch('/api/executions').then(r => r.json()).catch(() => null);
    if (execJson) {
      if (execJson.open.length > 0) {
        let h = '<div class="tbl-container"><table><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th><th>Corr ID</th></tr>';
        for (const o of execJson.open) {
          h += '<tr><td>' + o.id.substring(0,8) + '</td><td>' + o.symbol + '</td><td>' + o.side + '</td><td>' + o.qty + '</td><td>' + o.status + '</td><td>' + (o.correlation_id||'').substring(0,8) + '</td></tr>';
        }
        h += '</table></div>';
        document.getElementById('execGrid').innerHTML = h;
      } else {
        document.getElementById('execGrid').innerHTML = '<div style="color:var(--text-dim);margin-bottom:24px;font-size:0.8rem">No active orders</div>';
      }

      if (Object.keys(execJson.slippage).length > 0) {
        let h = '<div class="tbl-container"><table><tr><th>Symbol | Strategy</th><th>Avg Slippage (bps)</th></tr>';
        for (const [k, v] of Object.entries(execJson.slippage)) {
          h += '<tr><td>' + k + '</td><td>' + v.toFixed(2) + '</td></tr>';
        }
        h += '</table></div>';
        document.getElementById('slippageGrid').innerHTML = h;
      } else {
        document.getElementById('slippageGrid').innerHTML = '<div style="color:var(--text-dim);margin-bottom:24px;font-size:0.8rem">No fill data</div>';
      }
    }

  } catch (e) {
    document.getElementById('agentGrid').innerHTML =
      '<div class="error-state"><div class="icon">&#9888;</div><div class="msg">Connection Error: ' + e.message + '</div></div>';
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
                body = system_metrics.prometheus_text(self._system).encode()
                ct = "text/plain; charset=utf-8"
                status = "200 OK"
            elif method == "GET" and path == "/api/metrics/json":
                body = json.dumps(system_metrics.snapshot()).encode()
                ct = "application/json"
                status = "200 OK"
            elif method == "GET" and path == "/api/executions":
                exec_agent = getattr(self._system, "execution", None)
                open_orders = []
                filled_orders = []
                if exec_agent:
                    for k, v in exec_agent._open_orders.items():
                        open_orders.append({
                            "id": k,
                            "symbol": v.instrument,
                            "side": v.side.value if hasattr(v.side, "value") else str(v.side),
                            "qty": v.quantity,
                            "price": v.data.get("price", 0),
                            "status": v.status.value if hasattr(v.status, "value") else str(v.status),
                            "correlation_id": v.metadata.correlation_id,
                            "timestamp": v.timestamp.isoformat()
                        })
                    for k, v_list in exec_agent._filled_orders.items():
                        for v in v_list:
                            filled_orders.append({
                                "id": v.order_id,
                                "symbol": v.instrument,
                                "side": v.side.value if hasattr(v.side, "value") else str(v.side),
                                "qty": v.fill_quantity,
                                "price": v.fill_price,
                                "commission": getattr(v, "commission", 0.0) or 0.0,
                                "slippage_bps": getattr(v, "slippage_bps", 0.0) or 0.0,
                                "strategy": v.strategy or "unknown",
                                "timestamp": v.timestamp.isoformat()
                            })
                
                slippage_stats = {}
                for f in filled_orders:
                    key = f"{f['symbol']} | {f['strategy']}"
                    if key not in slippage_stats:
                        slippage_stats[key] = {"count": 0, "total_bps": 0}
                    slippage_stats[key]["count"] += 1
                    slippage_stats[key]["total_bps"] += f["slippage_bps"]
                
                body = json.dumps({
                    "open": open_orders,
                    "filled": filled_orders,
                    "slippage": {k: v["total_bps"]/v["count"] for k, v in slippage_stats.items()}
                }).encode()
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
                f"Access-Control-Allow-Origin: *\r\n"
                "\r\n"
            ).encode() + body
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.warning("Dashboard request error: %s", e)
        finally:
            writer.close()
