# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> **2026-06-07**: This changelog was reconstructed from `git log` (52
> commits) and the 2026-06-07 audit findings. The previous version
> only covered Phase 1; everything between Phase 1 and the current
> audit remediation was unrecorded.

## [Unreleased]

### 2026-06-07 — Audit Remediation Wave 1 (security, in progress)
#### Security
- **Task 2** (`d077c57`): Externalized hardcoded Telegram `CHAT_ID`
  (`8555799588`) and API URL from `monitor.py` to `MONITOR_CHAT_ID` /
  `MONITOR_API_URL` env vars; added `--dry-run` mode and digit-only
  validation. (PII was leaking in `monitor.py:7`.)
- **Task 4** (`de068ca`): Enforced `TRA_HTTP_AUTH_TOKEN` in
  `docker-compose.yml` via `${VAR:?error_msg}` syntax; added
  `WARNING` logs in `src/main.py:21` and `dashboard/server.py:28`
  when the token is empty. The `/api/kill-switch/reset` endpoint
  was previously UNAUTHENTICATED if the env var was unset.
- **Task 1** (`296e47e`): Added `scripts/verify_no_secrets.{ps1,sh}`
  to detect credential leaks in committed files; documented pending
  history scrub of the leaked `k1bpotx2f133yrms` token in
  `SECURITY.md`. (Full `git filter-branch` scrub is a shared-impact
  action and requires explicit user confirmation.)
- **Task 3** (`555fbeb`): Added `[vault]` optional extra to
  `pyproject.toml` (`boto3>=1.34`, `hvac>=2.0`); `src/utils/vault.py`
  now raises `RuntimeError` when the SDK is missing instead of
  silently warning.

#### Build / Tooling
- **Task 5** (`edca58c`): Removed nonexistent `kafka` service from
  `Makefile` `db-up` target — `docker-compose.yml` defines only
  `postgres` and `redis`.
- **Task 6** (`9d3b7ba`): Added explicit `*.db-shm`, `*.db-wal`,
  `/state/test_*.db`, `/state/probe_*.db` to `.gitignore` (defensive:
  existing `*.db*` already catches them). Verified all 16 leak-prone
  paths via `git check-ignore`.

#### Documentation
- **Task 7** (`54c6e4d`): Rewrote `init.md` to match the actual
  pure-Python 3.12 architecture (the original claimed Rust/Go/Kafka/
  Flink/K8s that was never built).

---

## [0.1.0] — 2026-06-05 — Paper Burn-in Launch
The system entered the 5-day paper-trading burn-in gate on 2026-06-05.
This release is what is currently running on Railway.

### 2026-06-07 — Paper burn-in launch infrastructure
- **(`5de0f54`)**: Paper burn-in launch infrastructure + security
  hardening; healthcheck, ntfy.sh notifications, Railway deployment.
- **(`8497a73`)**: Added `adx_filter`, `ema_regime`, `vwap_reversion`
  strategies to `src/strategies/`.

### 2026-06-07 — Phase 1 audit recovery
- **(`59f1ac1`)**: Fix `SyncEventBus` event ordering, SL emission,
  and test isolation gaps found in the 2026-06-02 audit.
- **(`82ca01d`)**: Research notes — free backtest data providers for
  NSE 1m/30m.

### 2026-06-05 — Three-stage roadmap completion (Stage 2 + Stage 3)
- **(`65e4229`)**: Completed Stage 2 SSOT (single source of truth
  for positions/orders) and Stage 3 infrastructure.
- **(`33a3ddb`)**: P1 SL `trigger_price` field + Position SSOT
  enforcement.
- **(`c938a36`)**: Delta audit — Stage 1 fixes vs prior audit claims.
- **(`50042a9`)**: Comparison of old `TRADE/` system vs new
  `new-trade` system.
- **(`a1adaa4`)**: Regime weight allocation uses multipliers
  (range [0.3, 2.0]) not absolute overrides.
- **(`99a24b2`)**: Backtest audit reveals `SyncEventBus` event-
  ordering bug (root cause of the Phase 1 recovery above).
- **(`72ae7d2`, `ebdd65f`)**: Stage 1 P0.1, P0.2, P0.4, P0.5 — unblock
  the execution path.

### 2026-06-04 — Stage 1 audit fixes merge
- **(`3babda8`)**: Deploy `strategy_gen` and safety/observability
  test suite.

### 2026-06-03 — Runtime safety gates + attribution
- **(`c4357ad`)**: Restore runtime safety gates; add
  `src/monitoring/attribution.py` for per-strategy PnL attribution.

### 2026-06-02 — Backtester + system audit
- **(`ede72c2`)**: Final audit fixes and report.
- **(`75ee77d`)**: Pass historical timestamps into event system;
  handle legacy strategies correctly.
- **(`834fdc1`)**: Resolve 0-trades bug in system backtester by
  using event time (not wall clock) for signal debouncing.
- **(`acc26ee`)**: Implement system backtester with strict data
  integrity checks.
- **(`2b7db8c`)**: Decrease regime sensitivity for Yahoo feed paper
  trading breakout.

---

## [0.0.5] — 2026-06-01 — Phase 1 Survival Fixes
### Critical fixes
- **(`73008e5`)**: Raise consensus threshold to 0.65; add regime
  broadcast on startup; gate `ReflectionEngine` mutations behind
  `TRA_REFLECTION_MUTATION_ENABLED` (off by default).
- **(`fc320d1`)**: Phase 1 survival bugs:
  - `ExecutionAgent` async locks (race on order submission)
  - RSI/Ichimoku calculation bugs (lookback window off-by-one)
  - `DecayDetector` async loop escape (hung on empty windows)
  - `pyproject.toml` `python` pin → `>=3.12,<3.13`
- **(`172d88b`)**: Kite API kwargs and event bus backpressure.
- **(`00b841a`)**: System-wide loss controls and regime debouncing
  in `src/risk/`.

### Tests + deploy
- **(`7cf8d50`, `d615339`)**: Test fixes — missing setup args,
  synthetic tick timestamps.
- **(`91c5e76`)**: Enable strategy and execution agents for
  in-hours trading only (9:15–15:30 IST).
- **(`f67fb43`)**: Fix Railway market data feed by polling Yahoo
  Finance (NSE direct feed blocked on Railway).

---

## [0.0.4] — 2026-05-26 — Dashboard Integration
### Frontend + deps
- **(`41ff49d`)**: Integrate React dashboard, multi-stage Docker
  build (Node 20 + Python 3.12).
- **(`4c363dd`)**: Local project state for deployment (SQLite
  default with `TRA_EVENT_STORE_TYPE=postgres` switch).
- **(`4542084`)**: `.gitignore` initial cleanup.
- **(`71c884e`, `8f0f4c1`, `692c53d`, `b65166d`, `f1dd0f3`)**:
  Various dep + config fixes — `node:20` for `node-gyp`/`better-
  sqlite3`, `feedparser` and `scipy` in core deps, dashboard extras
  (`fastapi`/`uvicorn`), enable Bollinger strategy in config.

---

## [0.0.3] — 2026-05-25 — Phase 5 Rebuild: Walk-Forward + Decay + CI
### (`6e6f273`) Phase 5 — added
- `src/backtest/walk_forward.py` — walk-forward optimization
- `src/agents/regime.py` — Regime Detection Agent
- `src/agents/decay_detector.py` — Performance Decay Detector
- `.github/workflows/ci.yml` — initial CI/CD (lint, type-check,
  test, ubuntu-only — to be expanded in Wave 3)
- `src/monitoring/observability.py` — structured metrics + traces
- `src/backtest/parameter_optimizer.py` — deterministic parameter
  search

---

## [0.0.2] — 2026-05-25 — Phase 4 Rebuild: Safety + Reconciliation
### (`277e031`) Phase 4 — added
- `src/risk/kill_switch.py` — Drawdown Kill-Switch (singleton,
  see Task 30 for refactor)
- `src/agents/reconciliation.py` — Position Reconciliation
  agent (skeleton; full impl Wave 7)
- `idempotent_orders` — `client_order_id` enforced end-to-end
- `retry_with_backoff` helper in `src/utils/`
- `AsyncSqliteEventStore` — concurrent-readers support
- `src/monitoring/http_dashboard.py` — Real-time dashboard
  (port 8080)
- `src/monitoring/alert.py` — alert rate limiting

---

## [0.0.2-pre] — 2026-05-25 — Phase 3 Rebuild: Costs + Vol Sizing
### (`f7beb6c`) Phase 3 — added
- Transaction-cost model in `src/execution/`
- Volatility-weighted position sizing
- `AsyncEventBus` (in-process pub/sub, replaces sync bus)
- SL/TP exits in `src/risk/`
- Consensus ensembling in `src/agents/strategy_gen.py`

---

## [0.0.1] — 2026-05-25 — Phase 1 & 2 Rebuild: Safety + Correctness
### (`7fa3ec1`) Phase 1 & 2 — added
- Critical safety and correctness improvements (per 2026-05-24
  audit):
  - Position reconciliation on startup
  - Order state machine (NEW → SUBMITTED → FILLED → CLOSED)
  - Pre-trade risk gate (max position, drawdown, leverage)
  - Idempotent order submission (`client_order_id`)
  - Heartbeat + liveness checks for all agents
  - Graceful shutdown handler

---

## [0.0.0] — 2026-05-24 — Initial Bootstrap
### (`b130aa9`) Dashboard integration
- Web dashboard mounted on the metrics server (port 8080).

### (`68c373a`) Initial commit
- Multi-agent trading system with `ntfy.sh` notifications,
  healthcheck endpoint, and Railway deployment target.
- 7-agent design (MarketIntel, StrategyGen, RiskManagement,
  Execution, Portfolio, Reconciliation, Alert).
- Event-sourced core: `Event` base class with 11 event types
  (Tick, OHLCV, Signal, Order, Fill, RiskCheck, Portfolio, System).
- Storage: `InMemoryEventStore`, `SqliteEventStore` (WAL mode,
  indexed), `PostgresEventStore` (TimescaleDB hypertable),
  `KafkaEventStore` (forward-compat only — not in hot path).
- Kite/Zerodha connector: `KiteClient`, `KiteMarketDataProvider`,
  `KiteBroker` with paper-mode fallback.
- Strategies: `Momentum`, `MeanReversion` built-in; pluggable
  strategy interface.
- 32 passing tests covering event store, schemas, and agent
  lifecycle.
- `plan.md` (master plan) + `init.md` (project overview,
  fictional Rust/Go architecture — corrected in Task 7).
- `Makefile` (install/lint/test/run-*), `docker-compose.yml`
  (TimescaleDB + Redis), `.env.example` (`TRA_` prefix).

---

[Unreleased]: https://github.com/aisathish07/new-trade/compare/54c6e4d...HEAD
[0.1.0]: https://github.com/aisathish07/new-trade/releases/tag/0.1.0-paper-burnin
[0.0.5]: https://github.com/aisathish07/new-trade/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/aisathish07/new-trade/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/aisathish07/new-trade/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/aisathish07/new-trade/compare/v0.0.1...v0.0.2
[0.0.0]: https://github.com/aisathish07/new-trade/releases/tag/v0.0.0
