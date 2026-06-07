# Operations

> **Audience**: on-call engineers, SRE, and operators responsible
> for deploying, monitoring, and recovering the `new-trade` paper
> trading system. For day-to-day *runtime* procedures (kill
> switch, watchlist, etc.), see [`RUNBOOK.md`](RUNBOOK.md). For
> system architecture, see [`ARCHITECTURE.md`](ARCHITECTURE.md).
> For developer setup, see [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Table of contents

1. [Local development setup](#1-local-development-setup)
2. [Docker Compose (postgres + redis + observability)](#2-docker-compose)
3. [Railway deploy (production paper run)](#3-railway-deploy)
4. [Monitoring setup (Prometheus + Grafana)](#4-monitoring-setup)
5. [Common failures](#5-common-failures)
6. [Recovery procedures](#6-recovery-procedures)
7. [Backup strategy](#7-backup-strategy)
8. [Disaster recovery](#8-disaster-recovery)

---

## 1. Local development setup

For a single-machine dev loop (no Docker required):

```bash
# 1. Clone + venv + install
git clone https://github.com/aisathish07/new-trade.git
cd new-trade
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS / Linux
pip install -e ".[dev,dashboard]"

# 2. Env
cp .env.example .env
# Edit .env to set MONITOR_* and TRA_HTTP_AUTH_TOKEN
# Generate the auth token:
python -c "import secrets; print(secrets.token_hex(32))"

# 3. Run
python -m src.main
# Server listens on :8080 (metrics + dashboard + control)
# State is SQLite at state/trading_events.db
```

The local SQLite path is `state/trading_events.db` (WAL mode,
single-writer / multi-reader). The default watchlist is
`RELIANCE,TCS,INFY,HDFCBANK`. The local run is **paper-only**;
the `TRA_LIVE_TRADING_ENABLED` env var is **not** set.

For dashboard hot-reload dev (Vite + FastAPI), run them in
two terminals:

```bash
# Terminal A: FastAPI backend
TRA_DASHBOARD=0 python -m src.main

# Terminal B: Vite frontend with HMR
cd dashboard
npm install
npm run dev
# Vite serves on :5173 with proxy to :8080
```

---

## 2. Docker Compose

`docker-compose.yml` ships 5 services. The current paper run
**does not** use the `trading-app` service in compose; it is
deployed to Railway instead. Local docker-compose is for the
**observability stack + storage** that local dev may want.

### Services

| Service | Image | Port | Purpose |
|---|---|---|---|
| `postgres` | `timescale/timescaledb:2-pg16` | 5432 | Optional Postgres (TimescaleDB hypertable for OHLCV); `tra_event_store_type=postgres` |
| `redis` | `redis:7-alpine` | 6379 | Optional Redis cache / pub-sub; not in hot path but available for connectors that need it |
| `prometheus` | `prom/prometheus:latest` | 9090 | Scrape target `trading-app:8080/metrics`; loads `prometheus_alerts.yml` |
| `grafana` | `grafana/grafana:latest` | 3000 | Dashboards; admin password from `GF_SECURITY_ADMIN_PASSWORD` env (use a non-default value!) |
| `trading-app` | (built from local `Dockerfile`) | 8080 | Local container; **the production burn-in runs on Railway**, not compose |

### Start / stop

```bash
# Start the storage + observability stack (no trading-app)
make db-up          # = docker compose up -d postgres redis

# Start the full stack including local trading-app
docker compose up -d

# Stop everything
make db-down        # = docker compose down

# Tail logs
docker compose logs -f --tail=200 trading-app
```

### Required env vars

The `trading-app` service in compose reads env from the host.
**`TRA_HTTP_AUTH_TOKEN` is required** (compose fails fast with
`${VAR:?error_msg}` if unset — see Task 4). The other vars
are optional with sensible defaults.

```
TRA_HTTP_AUTH_TOKEN=<32-byte hex>          # REQUIRED
TRA_EVENT_STORE_TYPE=postgres              # default: sqlite
TRA_POSTGRES_DSN=postgresql+asyncpg://trading:trading@postgres:5432/trading
TRA_REDIS_URL=redis://redis:6379/0
TRA_LOG_LEVEL=INFO
TRA_WATCHLIST=RELIANCE,TCS,INFY,HDFCBANK
# + broker creds as needed (TRA_KITE_*, TRA_GROWW_*, etc.)
```

> The default `trading` / `trading` / `trading` postgres
> credentials in `docker-compose.yml` are **local-dev only**.
> For anything else, override via `POSTGRES_PASSWORD` env or an
> `env_file: .env`. See Section 8 for the credential rotation
> procedure.

### Health checks

The `trading-app` Dockerfile declares a `HEALTHCHECK` that hits
`/health` every 30 s, timeout 10 s, 3 retries, 15 s start
period. The compose `trading-app.depends_on` clauses wait for
`postgres` and `redis` to report healthy before starting.

---

## 3. Railway Deploy

The current 5-day paper burn-in (started 2026-06-05) runs on
[Railway](https://railway.app). `railway.json` is the deploy
manifest.

### Build

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "numReplicas": 1,
    "sleepApplication": false,
    "restartPolicyType": "ALWAYS",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 30
  }
}
```

- **numReplicas: 1** — single instance; the event store is
  single-writer (SQLite by default; switch to Postgres for HA
  in a future wave).
- **restartPolicyType: ALWAYS** — Railway restarts the
  container on crash, OOM, or deploy.
- **healthcheckPath: /health** — see `Dockerfile` HEALTHCHECK
  directive; Railway's healthcheck is independent (30 s
  timeout).

### Dockerfile (2-stage)

```
Stage 1 (node:20):
  - npm install in /app/dashboard
  - npm run build → /app/dashboard/dist
Stage 2 (python:3.12-slim):
  - copy dist from Stage 1
  - pip install --no-cache-dir .[dashboard]
  - EXPOSE 8080
  - HEALTHCHECK /health
  - CMD ["python", "-m", "src.main"]
```

The `python:3.12-slim` image is ~150 MB; the multi-stage build
is what keeps the final image small by *not* shipping `node`
or `npm` to runtime.

### Env vars on Railway

Set via Railway dashboard → Variables. **Do not** check them
into git. Required:

| Var | Required | Notes |
|---|---|---|
| `TRA_HTTP_AUTH_TOKEN` | YES | Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TRA_EVENT_STORE_TYPE` | NO | `sqlite` (default) or `postgres` |
| `TRA_LOG_LEVEL` | NO | `INFO` (default) |
| `MONITOR_BOT_TOKEN` | YES for alerts | Telegram bot token (from @BotFather) |
| `MONITOR_CHAT_ID` | YES for alerts | Telegram chat ID |
| `TRA_KITE_*` | For live Kite | Set only when `TRA_LIVE_TRADING_ENABLED=true` |
| `TRA_GROWW_*` | For live Groww | Set only when `TRA_LIVE_TRADING_ENABLED=true` |
| `PORT` | Auto-set by Railway | The `python -m src.main` server reads it |

### Deploy workflow

```bash
# 1. Make sure local is clean
git status
make lint && make test

# 2. Push (Railway auto-builds on push to master)
git push origin master

# 3. Watch the deploy
railway logs --tail

# 4. Verify health
curl -sS https://<your-app>.up.railway.app/health
# -> {"status": "ok", ...}

# 5. Verify metrics
curl -sS https://<your-app>.up.railway.app/metrics | head -n 5
```

### Rollback

```bash
# Option A: revert the commit + push
git revert <bad-commit-sha>
git push origin master

# Option B: re-deploy a previous commit
# (Railway dashboard → Deployments → click prior deploy → "Redeploy")
```

The event store is **durable across deploys** because Railway
preserves the container's persistent volume for `state/`. A
redeploy does NOT wipe fills or signals.

---

## 4. Monitoring setup

### Prometheus

`prometheus.yml` (12 lines):

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/prometheus_alerts.yml

scrape_configs:
  - job_name: "trading-system"
    static_configs:
      - targets: ["trading-app:8080"]
    metrics_path: "/metrics"
```

- **scrape_interval: 15s** — every 15 s Prometheus pulls
  `/metrics` from the trading app.
- **rule_files** — loads `prometheus_alerts.yml` (3 alerts
  today; Wave 4 Task 25 will grow to 10+).
- **target** — `trading-app:8080` in compose; on Railway the
  target is the same hostname internally.

### Current alerts (`prometheus_alerts.yml`)

| Alert | Severity | Condition | For |
|---|---|---|---|
| `TradingSystemDown` | critical | `up == 0` or no heartbeat in 60 s | 1m |
| `KillSwitchTriggered` | warning | `trading_kill_switch_active == 1` | 0s |
| `BrokerConnectionLost` | critical | `trading_broker_connected == 0` | 10s |

### Grafana

Compose ships Grafana on `:3000`. To set up a dashboard:

1. Open `http://localhost:3000` and log in with the admin
   password from `GF_SECURITY_ADMIN_PASSWORD` env.
2. **Add a Prometheus data source**:
   - Type: Prometheus
   - URL: `http://prometheus:9090` (in compose) or your
     Railway-exposed Prometheus URL
3. **Add the TimescaleDB plugin** (auto-installed in compose
   via `GF_INSTALL_PLUGINS=timescaledb`):
   - Type: TimescaleDB
   - URL: `postgres://trading:trading@postgres:5432/trading`
4. **Import a dashboard** for trading metrics (key panels):
   - `trading_uptime_seconds` — single-stat
   - `trading_kill_switch_active` — single-stat with red
     threshold
   - `rate(trading_orders_total[5m])` — orders per second
   - `rate(trading_fills_total[5m])` — fills per second
   - `rate(trading_risk_vetoes_total[5m])` — risk vetoes
   - `trading_open_positions` — gauge
   - `trading_pnl_session` — single-stat with green/red
     threshold
   - `histogram_quantile(0.95, rate(trading_latency_ms_bucket[5m]))`
     — p95 latency

> **Do not** use the default `admin` / `admin` Grafana
> credentials in any non-local environment. Override
> `GF_SECURITY_ADMIN_PASSWORD` in `docker-compose.yml` or via
> the `env_file: .env` mechanism.

### Local monitoring stack

```bash
make db-up                                    # postgres + redis
docker compose up -d prometheus grafana       # observability
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000
```

---

## 5. Common failures

### 5.1 Container won't start

| Symptom | Likely cause | Action |
|---|---|---|
| `docker compose up` exits immediately | `TRA_HTTP_AUTH_TOKEN` unset | Set it; see Task 4 (`${VAR:?error_msg}`) |
| `ERROR: service 'kafka' not found` | Old `make db-up` recipe | Already fixed in Task 5; pull latest |
| `port 8080 already in use` | Local Python process holding the port | `Get-Process python` → kill, or change `PORT` env |
| Health check 503s | DB unreachable | Check `docker compose ps`; restart `postgres` |

### 5.2 No signals firing

See [`RUNBOOK.md`](RUNBOOK.md) Section 6. Summary:
- Cold-start: signals block until ~12:35 IST
- Regime filter blocking: check `adx_filter` / `ema200_regime_gate`
- Watchlist mismatch: check `TRA_WATCHLIST`
- Kill switch active: see [`RUNBOOK.md`](RUNBOOK.md) Section 1

### 5.3 Broker API errors

| Broker | Common error | Action |
|---|---|---|
| Kite | `TokenException` | Access token expired at 6 AM IST; see [`RUNBOOK.md`](RUNBOOK.md) Section 3 |
| Kite | `NetworkException` | Kite API down; wait + retry; check https://kite.zerodha.com |
| Angel | `InvalidToken` | Refresh token flow; check `TRA_ANGEL_*` env |
| Groww | `TOTPInvalid` | Re-check `TRA_GROWW_TOTP_SECRET` (no spaces) |

### 5.4 Prometheus alert: TradingSystemDown

1. Check Railway dashboard → Service logs
2. Check `state/burnin/stderr.log` for the most recent
   Python traceback
3. Check the most recent commit on `master` — was a bad
   deploy pushed?
4. If needed, `railway restart` (or `docker compose restart
   trading-app` locally)
5. If the issue is data corruption, see Section 8 (Disaster
   Recovery)

### 5.5 Database locked

`sqlite3.OperationalError: database is locked` means a
long-running reader or writer is blocking:

```bash
# Find and kill rogue sqlite3 sessions
ps -ef | grep sqlite3

# Or on Windows:
Get-Process python | Where-Object { $_.MainWindowTitle -match "sqlite" }
```

The fix is rarely to `rm` the DB — see Section 6.

### 5.6 State files grow without bound

| File | Typical size | Mitigation |
|---|---|---|
| `state/trading_events.db` | 35 MB (after 1 burn-in) | Wave 4 Task 26 will add a 30-day retention policy; for now, `sqlite3 ... "VACUUM;"` after manual prune |
| `state/angel_symbols.json` | 26.6 MB | Wave 4 Task 26 will add TTL; rebuild via Section 6 procedure |
| `state/order_state.db-wal` | 4 MB | Normal; auto-checkpointed; `state/order_state.db-shm` is in-memory |
| `logs/runtime_traces/*.jsonl` | ~1 MB/day | Wave 4 Task 26 will rotate; for now, `Remove-Item logs\runtime_traces\trace_*.jsonl -Exclude trace_*.today.jsonl` |

---

## 6. Recovery procedures

### 6.1 SQLite event-log corruption

`state/trading_events.db` is the **durable audit trail** of
every signal, order, fill, and risk event. If it is corrupt:

```bash
# 1. STOP the trading system first
./scripts/stop_paper_burnin.ps1

# 2. Try to repair with sqlite3's integrity_check
sqlite3 state/trading_events.db "PRAGMA integrity_check;"
# If it returns "ok" -> not corrupt
# If it returns errors -> proceed to step 3

# 3. Try to clone what is salvageable
sqlite3 state/trading_events.db ".clone state/trading_events.db.recovered"

# 4. Verify the recovered DB
sqlite3 state/trading_events.db.recovered "PRAGMA integrity_check;"
sqlite3 state/trading_events.db.recovered "SELECT COUNT(*) FROM events;"

# 5. If recovered DB is good, swap
mv state/trading_events.db state/trading_events.db.corrupt.$(date +%Y%m%d)
mv state/trading_events.db.recovered state/trading_events.db

# 6. Restart
./scripts/start_paper_burnin.ps1
```

> **Do NOT `rm state/trading_events.db` to "start fresh".**
> The event log is the only source of truth for fills; without
> it, the paper-burn-in gate is unverifiable. A clean restart
> would re-emit only *future* events; past PnL attribution
> becomes impossible.

### 6.2 Postgres (TimescaleDB) corruption

If the production burn-in is using Postgres (Wave 8 Task 49
will move there) and the database is corrupt:

1. Stop the trading app first (`railway stop` or compose
   stop).
2. Restore from the most recent nightly backup (Section 7).
3. If no backup exists, run `VACUUM FULL` + `REINDEX` to
   rebuild indexes. For *table*-level corruption, drop and
   recreate; the schema migrations in `src/event_store/postgres.py`
   are idempotent.
4. Restart; the system will rebuild in-memory state from
   events.

### 6.3 Stuck reconciliation

See [`RUNBOOK.md`](RUNBOOK.md) Section 4.

### 6.4 `angel_symbols.json` corruption

See [`RUNBOOK.md`](RUNBOOK.md) Section 5.

### 6.5 Roll back a bad deploy

1. Identify the bad commit: `git log --oneline -20`
2. `git revert <bad-commit-sha>`
3. `git push origin master` — Railway auto-deploys the revert
4. Verify: `curl -sS https://<app>.up.railway.app/health`
5. The event store is **not** rolled back (it is durable);
   only the code is.

### 6.6 Lost Kite access token

See [`RUNBOOK.md`](RUNBOOK.md) Section 3.

---

## 7. Backup strategy

### What to back up

| Asset | Frequency | Storage | Retention |
|---|---|---|---|
| `state/trading_events.db` | Nightly (cron / GitHub Action) | Cloud object store (S3 / R2 / Railway volume snapshot) | 90 days |
| `state/order_state.db` | Nightly | Same as above | 90 days |
| `state/burnin/reconciliation.jsonl` | Nightly | Same as above | 1 year (for burn-in audit) |
| `state/angel_symbols.json` | Weekly (it changes rarely) | Same as above | 30 days |
| `state/burnin/metadata.json` | Nightly | Same as above | 1 year |
| `.env` | **NEVER** — store in 1Password / Vault / Railway env | n/a | n/a |
| `state/kite_token.json` | **NEVER** — only on disk on the running container | n/a | n/a (regenerated) |

### Backup script (template)

```bash
#!/usr/bin/env pwsh
# scripts/backup_state.ps1 — run nightly via cron / Railway scheduled task
$ErrorActionPreference = "Stop"
$StateDir = "state"
$BackupRoot = "s3://my-bucket/new-trade-backups"
$Date = (Get-Date -Format "yyyy-MM-dd")

# 1. Stop writes briefly with sqlite3 .backup command (online, no lock)
$TmpDir = New-Item -ItemType Directory -Path "$StateDir/.backup-$Date" -Force
sqlite3 "$StateDir/trading_events.db" ".backup '$TmpDir/trading_events.db'"
sqlite3 "$StateDir/order_state.db"     ".backup '$TmpDir/order_state.db'"
Copy-Item "$StateDir/burnin/*"          "$TmpDir/"

# 2. Compress
$Archive = "$StateDir/backup-$Date.tar.gz"
tar -czf $Archive -C $StateDir ".backup-$Date"
Remove-Item -Recurse $TmpDir

# 3. Upload
aws s3 cp $Archive "$BackupRoot/$Date/"

# 4. Prune local
Remove-Item $Archive
```

### Recovery from backup

```bash
# Download
aws s3 cp s3://my-bucket/new-trade-backups/2026-06-07/backup-2026-06-07.tar.gz .

# Extract
tar -xzf backup-2026-06-07.tar.gz

# Replace state
./scripts/stop_paper_burnin.ps1
cp -r .backup-2026-06-07/* state/
./scripts/start_paper_burnin.ps1
```

> Backups are encrypted at rest by S3 (or your equivalent
> object store). Do not add a separate encryption layer unless
> required by your compliance regime.

### Test backups monthly

A backup you have never restored is a backup you do not have.
Schedule a monthly restore drill:

```bash
# In a disposable environment
docker compose up -d postgres
createdb -h localhost -U trading trading_restore
psql -h localhost -U trading -d trading_restore < backup.sql
# Verify event count
psql -h localhost -U trading -d trading_restore -c "SELECT COUNT(*) FROM events;"
```

---

## 8. Disaster recovery

This section covers the *worst case* scenarios: full data
loss, region outage, broker compromise. Most operators will
never need this; it exists so that if you do, the answer is
already written down.

### 8.1 Total state directory loss

If `state/` is wiped (e.g., `rm -rf` mistake, volume lost):

1. **Stop the system** if not already stopped.
2. **Restore from the most recent backup** (Section 7).
3. If no backup exists: the system is **cold-start only**.
   You must:
   - Acknowledge to stakeholders that the burn-in is
     invalidated; the 5-day clock restarts from the next
     session open.
   - Reset the kill switch (it was in-memory; will be reset
     on next start anyway).
   - Manually re-validate the watchlist, broker selection,
     and env vars.
4. **Document the loss** in `state/burnin/incidents/<date>-
   state-loss.md` for the burn-in audit.

### 8.2 Broker compromise (stolen API key)

1. **Revoke the API key at the broker**:
   - Kite: https://kite.zerodha.com → Profile → My apps →
     Disable
   - Groww: Groww mobile app → Settings → API → Disable
   - Angel: Angel One → Profile → API → Disable
2. **Generate a new key** and update Railway env vars
   (do **not** commit to git).
3. **Restart the system** to pick up the new key.
4. **Rotate `TRA_HTTP_AUTH_TOKEN`** (the Bearer token for
   control endpoints) as well — if the broker key was
   stolen, the attacker may have had access to the
   dashboard.
5. **Audit the event log** for unauthorized actions:
   ```bash
   sqlite3 state/trading_events.db "SELECT * FROM events \
   WHERE ts > '2026-06-05 00:00:00' \
   AND event_type IN ('ORDER', 'FILL', 'KILL_SWITCH') \
   ORDER BY ts;"
   ```
6. **Document the incident** in `state/burnin/incidents/`
   and in your broker's incident log (Kite/Groww/Angel all
   have one).

### 8.3 Region outage (Railway down)

Railway's `restartPolicyType: ALWAYS` will restart the
container as soon as the region is back. There is nothing
to do during a region outage *unless* the outage exceeds
the broker session timeout (e.g., Kite tokens are valid 6
AM–6 AM IST, so an outage that spans the rollover will
require re-auth).

For long outages (>4 h):
1. Acknowledge to stakeholders.
2. When Railway recovers, verify the burn-in is still
   emitting heartbeats (`/health` and `/api/agents/health`).
3. If the system is stuck, follow [`RUNBOOK.md`](RUNBOOK.md)
   Section 4 (stuck reconciliation).
4. The burn-in gate (5 calendar days) is paused during the
   outage; resume counting from recovery.

### 8.4 Container OOM-killed

If Railway shows `OOMKilled`:

1. Check `docker stats` (locally) or Railway metrics for
   memory at the time of kill.
2. Likely culprits:
   - `state/trading_events.db` is being held in memory by a
     long-running query (it is 35 MB; not normally an issue).
   - `state/angel_symbols.json` (26 MB) loaded into memory
     at startup.
   - A misbehaving agent accumulating state.
3. Mitigations:
   - Increase Railway memory to 1 GB (default is 512 MB).
   - Wave 4 Task 21 will persist metrics to disk (currently
     in-memory).
   - Wave 4 Task 26 will add a state-file retention policy.

### 8.5 Git history corruption (force-push gone wrong)

1. If you or a collaborator `git push --force`d to
   `master`, the remote reflog is the only source of truth.
2. `git reflog` on a fresh clone shows the pre-force commits
   for up to 90 days.
3. Recover with:
   ```bash
   git reflog                                            # find the lost SHA
   git reset --hard <lost-sha>                           # local restore
   git push --force-with-lease origin master             # restore remote
   ```
4. **Prevention**: never `--force` to `master`; force-push
   only to your own feature branch.

### 8.6 Contact + escalation

| Severity | Contact | Response time |
|---|---|---|
| Critical (live trading PnL at risk, broker compromise) | On-call + broker | < 15 min |
| High (paper burn-in down, kill switch stuck) | On-call | < 1 h |
| Medium (degraded monitoring, slow queries) | Next business day | < 8 h |
| Low (docs, non-blocking warnings) | Next sprint | < 1 week |

This is a *paper trading* system. The 5-day burn-in is the
safety mechanism; the 4-hour post-burn-in manual review is
the second safety mechanism. Live trading is **off** until
[`live_trading_gate.md`](live_trading_gate.md) is signed off.

---

## Quick reference: ports

| Port | Service | Bind |
|---|---|---|
| 8080 | FastAPI metrics + dashboard + control | `0.0.0.0` |
| 5432 | Postgres (TimescaleDB) | `127.0.0.1` (compose) |
| 6379 | Redis | `127.0.0.1` (compose) |
| 9090 | Prometheus | `0.0.0.0` (compose) |
| 3000 | Grafana | `0.0.0.0` (compose) |
| 5173 | Vite dev server (local only) | `127.0.0.1` |

## Quick reference: compose service dependencies

```
trading-app
├── postgres   (healthy)
└── redis      (healthy)

grafana
└── prometheus
```

`trading-app` waits for `postgres` and `redis` to be
`service_healthy` before starting. `grafana` waits for
`prometheus` to start (but not for healthy).
