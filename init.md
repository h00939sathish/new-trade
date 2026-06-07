# Project Initialization

> **Rewritten 2026-06-07**: This `init.md` was rewritten on 2026-06-07 to
> match the actual codebase. The original described a planned
> Rust/Go/Kafka/Flink/K8s architecture that was **never built**. The
> actual system is a pure-Python 3.12 multi-agent trading platform. For
> the full architecture, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Overview

`new-trade` is a multi-agent, event-sourced, paper-trading system for the
National Stock Exchange of India (NSE). It is designed and built as a
single Python 3.12 codebase with a FastAPI/React dashboard, SQLite/Postgres
storage, and pluggable data connectors.

The system runs as a paper-trading burn-in (5-day minimum gate) before
any live-trading consideration. The current burn-in started 2026-06-05
and is the active validation path; see `docs/live_trading_gate.md`.

## Tech Stack (actual)

### Core
- **Language**: Python 3.12 (3.12.x only; 3.13+ not supported)
- **Async runtime**: `asyncio` + `httpx` for I/O
- **Validation/config**: `pydantic>=2.0`, `pydantic-settings>=2.0`
- **CLI UX**: `rich>=13.0`

### Data + Storage
- **Time-series DB**: TimescaleDB (Postgres 16) — `asyncpg>=0.29`
- **Cache / state**: Redis 7 — `redis[hiredis]>=5.0`
- **Local event store**: SQLite via `aiosqlite>=0.22.1` (default;
  switches to Postgres when `TRA_EVENT_STORE_TYPE=postgres`)
- **Data wrangling**: `pandas>=2.0`, `numpy>=1.26`, `scipy>=1.13`

### Data Connectors (3)
- `yahoo.py` — Yahoo Finance historical OHLCV (free fallback)
- `alternative_data.py` — RSS/news sentiment + earnings calendar
- `backtest_provider.py` — historical replay data source
- *(The "5 broker connectors" claim in the plan refers to broker
  **adapter stubs** in `src/connectors/` plus kiteconnect + Groww TOTP
  auth in `src/auth/`. True multi-broker live routing is **not** yet
  shipped — the active paper run uses the yahoo/backtest providers.)*

### Strategies (14 implementations; 3 active)
Located in `src/strategies/`. Active set (from
[`docs/active_strategy_set.md`](docs/active_strategy_set.md)):
- `momentum` (trend, weight 0.40) — `tsmom.py`
- `sideways_reversion` (reversion, weight 0.35) — `sideways_reversion.py`
- `vwap_reversion` (reversion, weight 0.25) — `vwap_reversion.py`

Filters (weight 0, block signals when condition fails):
- `ema200_regime_gate` — `ema_regime.py`
- `adx_regime_filter` — `adx_filter.py`

Disabled in `__init__.py` `ignore_list`: `pca_statarb`, `ml_regime`, `stat_arb`.

### Agents (11, in `src/agents/`)
- `market_intel` — ingest market data, compute regimes
- `regime` — classify market regime (trending/mean-reverting/volatile)
- `strategy_gen` — generate signals from active strategy set
- `risk_mgmt` — pre-trade risk validation, exposure, kill switch
- `execution` — order routing (paper; 1,377-line module slated for
  Wave 6 split into `OrderRepository` / `PaperFillSimulator` /
  `TwapIcebergEngine` / `SignalQueue` / `ExecutionCore`)
- `portfolio` — positions, PnL, exposure tracking
- `reconciliation` — broker fill reconciliation (planned Wave 7)
- `reflection_engine` — strategy mutation proposal engine (backtest-gated
  in Wave 7)
- `personas` — operator-persona simulated decisioning
- `alert` — Telegram/email alerts (`monitor.py` cron-like companion)
- `base` — shared agent base class

### Dashboard
- Backend: `dashboard/server.py` — FastAPI (`fastapi>=0.115`,
  `uvicorn[standard]>=0.30`) on port 8080
- Frontend: `dashboard/src/` — React + TypeScript + Vite
- Control plane: `dashboard/control_plane/` — kill-switch, position
  flatten, regime override, dry-run toggle (all behind
  `TRA_HTTP_AUTH_TOKEN` Bearer auth)
- Built artifact: `dashboard/dist/` (Vite build output)

### Observability
- **Metrics**: in-process Prometheus-compatible text exporter at
  `/metrics` (port 8080); backed by `src/monitoring/metrics.py`
  *(in-memory only — Wave 4 task 21 will persist)*
- **Tracing**: `src/monitoring/latency_tracer.py` for hot-path latency
- **Logging**: stdlib `logging` with `TRA_LOG_LEVEL` env var
- **Dashboards**: Prometheus + Grafana (compose services; admin/admin)
- **Alerts**: `prometheus_alerts.yml` (3 alerts, will grow to 10+ in
  Wave 4)

### Auth + Secrets
- `src/auth/groww_totp.py` — Groww TOTP login flow
- `src/auth/kite_session.py` — Zerodha Kite session management
- `src/utils/vault.py` — secret retrieval (env → file → AWS/GCP vault);
  raises `RuntimeError` if `boto3`/`hvac` extras not installed (Task 3)
- Telegram bot config via `MONITOR_BOT_TOKEN` / `MONITOR_CHAT_ID`
  (formerly hardcoded — Task 2)

### Optional Extras (`pip install -e ".[extra]"`)
- `dev` — pytest, ruff, mypy, pre-commit
- `kite` — `kiteconnect>=5.0` for Zerodha broker
- `ml` — scikit-learn, lightgbm, torch
- `streaming` — `apache-flink` (transitive compat only; not actively used)
- `dashboard` — FastAPI/uvicorn (auto-installed in dev image)
- `vault` — `boto3>=1.34`, `hvac>=2.0` (Task 3)

## Project Structure (actual)

```
new-trade/
├── init.md                # This file — high-level overview + conventions
├── CHANGELOG.md           # Human-curated change log
├── plan.md                # Post-audit plan (2026-06-02) — paper run gate
├── pyproject.toml         # Single source of dependency truth
├── docker-compose.yml     # postgres, redis, prometheus, grafana, app
├── Makefile               # install / dev / lint / test / db-up / run-*
├── .env.example           # Documented env var template
├── .env.compose.example   # Compose-only env vars (Task 4)
├── monitor.py             # Cron-like Telegram monitor (uses MONITOR_* env)
├── scripts/               # replay, verify, scrub, smoke-test scripts
├── src/
│   ├── auth/              # kite_session, groww_totp
│   ├── config/            # settings, strategy_config, env loader
│   ├── connectors/        # yahoo, alternative_data, backtest_provider
│   ├── core/              # event types, base classes, exceptions
│   ├── event_store/       # SQLite/Postgres event store
│   ├── agents/            # 11 agents (see above)
│   ├── strategies/        # 14 strategies, 3 active
│   ├── risk/              # kill_switch, position_limits, exposure
│   ├── portfolio/         # positions, PnL
│   ├── execution/         # execution helpers (split target in Wave 6)
│   ├── monitoring/        # metrics, dashboard, burnin, latency, attribution
│   ├── ml/                # regime classifiers, feature builders
│   ├── backtest/          # backtest engine, replay harness
│   ├── analytics/         # attribution, decay detection
│   ├── mcp_tools/         # model-context-protocol tool adapters
│   ├── agentic/           # agent-orchestration helpers
│   ├── schemas/           # pydantic schemas for events/orders
│   └── utils/             # vault, time, retry, json helpers
├── tests/                 # 56 test files, 329 tests passing
├── dashboard/
│   ├── server.py          # FastAPI control + metrics server
│   ├── control_plane/     # kill-switch / flatten / override endpoints
│   ├── src/               # React frontend
│   ├── dist/              # Built frontend (gitignored)
│   └── package.json
├── docs/
│   ├── INDEX.md           # Doc cross-reference (Task 9)
│   ├── ARCHITECTURE.md    # Real architecture (Task 10)
│   ├── RUNBOOK.md         # Operational guide (Task 11)
│   ├── CONTRIBUTING.md    # Dev guide (Task 12)
│   ├── OPERATIONS.md      # Deploy/monitor/recover (Task 13)
│   ├── live_trading_gate.md  # 5-day paper run gate
│   └── active_strategy_set.md
├── prometheus.yml         # Prometheus scrape config
├── prometheus_alerts.yml  # 3 alerts (Wave 4 will grow)
├── state/                 # gitignored runtime: trading_events.db,
│                          #   order_state.db, angel_symbols.json, burnin/
├── logs/                  # gitignored runtime traces
├── data/                  # gitignored historical data cache
└── .omo/                  # OpenCode session artifacts (plans, evidence)
```

## Conventions (still valid)

- All agent communication via the **in-process event bus**
  (`src/core/event_bus.py`) — *not* Kafka. The Kafka client
  (`aiokafka>=0.10`) is installed for the optional streaming backend
  (Wave 8 / Phase 3) but is not in the hot path.
- **Event sourcing** for every state change (orders, fills, signals,
  regime flips, agent heartbeats)
- **Deterministic replay** from the event store via
  `scripts/replay_events.py` and `src/backtest/`
- Strategies are pure functions of `(market_state, regime, params)` —
  no shared mutable state, safe to replay
- **Pre-trade risk validation** in `src/risk/` is mandatory for every
  order; risk_mgmt agent vetoes before execution
- **Every component** emits metrics (counters, gauges, histograms) via
  `src/monitoring/metrics.py`
- **Every change** is recorded in `CHANGELOG.md` (now updated in
  Task 8)
- **Idempotent order IDs**: client_order_id is required and de-duped
  to make paper + live re-runs safe

## Getting Started

1. **Read first**:
   - `plan.md` — post-audit 5-day paper run plan (2026-06-02)
   - `docs/ARCHITECTURE.md` — real Python architecture (Task 10)
   - `docs/live_trading_gate.md` — promotion criteria from paper to live
2. **Setup**:
   ```bash
   cp .env.example .env       # edit secrets (MONITOR_*, TRA_KITE_*, etc.)
   pip install -e ".[dev,dashboard,vault]"
   make db-up                  # postgres + redis
   make test                   # 329 tests
   ```
3. **Run the paper burn-in**:
   ```bash
   python -m src.main
   ```
4. **Operate**:
   - See `docs/RUNBOOK.md` for daily checks
   - See `docs/OPERATIONS.md` for deploy/recover procedures
5. **Contribute**:
   - See `docs/CONTRIBUTING.md` (Task 12)
6. **After code changes**:
   ```bash
   ruff check src/
   mypy src/
   pytest tests/ --cov=src
   ```

## Knowledge Graph (graphify)

This project uses [graphify](file:///C:/Users/h0093/.config/opencode/skills/graphify/SKILL.md)
to maintain a queryable knowledge graph of the codebase. After making
changes, run the `graphify` skill (or `/graphify .` if a slash
command is registered) to refresh `graphify-out/`.

The previous `init.md` claimed graphify is auto-run on every change;
that is not yet enforced (planned as a pre-commit hook in Task 12).
