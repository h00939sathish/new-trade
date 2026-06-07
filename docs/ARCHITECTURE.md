# Architecture

> **Audience**: engineers, operators, and reviewers. This is the
> current-truth architectural reference for `new-trade` as of
> 2026-06-07. The previous `init.md` described a planned Rust /
> Go / Kafka / Flink / K8s architecture that **was never built**.
> For the high-level overview and conventions, see
> [`init.md`](../init.md). For the strategic plan and timeline, see
> [`plan.md`](../plan.md). For the audit that drove the current
> remediation work, see
> [`trading_engine_audit_2026-06-02.md`](trading_engine_audit_2026-06-02.md).

## System overview

`new-trade` is a **pure-Python 3.12**, **event-sourced**,
**multi-agent** NSE (National Stock Exchange of India) paper-trading
platform. It is a single process per agent, communicating via an
**in-process async event bus**, persisting every state change to
either SQLite (default, local dev) or Postgres / TimescaleDB
(production). The system runs as a paper burn-in; live trading is
**not yet enabled** (see
[`live_trading_gate.md`](live_trading_gate.md)).

The system is structured as **11 long-running agents** that
subscribe to typed events, mutate their own state, and emit new
events. There is **no central orchestrator** in the hot path — the
bus is the spine. The single `TradingSystem` class
(`src/system.py`) is responsible for wiring the agents together at
startup, not for runtime control.

```
                ┌──────────────────────────────────────────────────────┐
                │                  src/main.py                         │
                │   (boot: load settings, start metrics, wire agents)  │
                └─────────────────────┬────────────────────────────────┘
                                      │
                                      ▼
              ┌───────────────────────────────────────────────────────┐
              │            src/system.py : TradingSystem              │
              │  (start/stop agents, expose /metrics, /api/kill-switch)│
              └─────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │                  src/event_store/async_bus.py                       │
   │       (in-process pub/sub, typed event channels, backpressure)      │
   │                                                                    │
   │  Channels:                                                         │
   │    market.*  →  Tick, OHLCV                                        │
   │    signal.*  →  Signal                                            │
   │    order.*   →  Order, Fill                                       │
   │    risk.*    →  RiskCheck, KillSwitch                             │
   │    portfolio.* → Portfolio, PnL                                   │
   │    system.*  →  Heartbeat, RegimeBroadcast                        │
   └──────┬─────────────┬─────────────┬─────────────┬──────────────────┘
          │             │             │             │
          ▼             ▼             ▼             ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ Market   │  │ Strategy │  │   Risk   │  │Execution │
   │  Intel   │─▶│   Gen    │─▶│   Mgmt   │─▶│  Agent   │
   │ (ingest) │  │ (signals)│  │  (gate)  │  │ (orders) │
   └──────────┘  └──────────┘  └──────────┘  └────┬─────┘
        │              │             │              │
        │              │             │              ▼
        │              │             │       ┌──────────────┐
        │              │             │       │   Broker     │
        │              │             │       │  Connector   │
        │              │             │       │ (paper/kite) │
        │              │             │       └──────┬───────┘
        │              │             │              │
        ▼              ▼             ▼              ▼
   ┌──────────────────────────────────────────────────────┐
   │           src/event_store/{sqlite,postgres,kafka}    │
   │   (durable log: every event appended; replayable)    │
   └──────────────────────────────────────────────────────┘
                            │
                            ▼
            ┌──────────────────────────────┐
            │  src/monitoring/metrics.py   │
            │  (Prometheus text on :8080)  │
            └──────────────────────────────┘
                            │
                            ▼
            ┌──────────────────────────────┐
            │  dashboard/server.py : FastAPI│
            │  + React (Vite/TS) frontend   │
            └──────────────────────────────┘
```

## Agents (`src/agents/`)

All agents extend `BaseAgent` (`src/agents/base.py`), which provides
async `start()` / `stop()` lifecycle, event-bus subscriptions, and
heartbeat emission. Heartbeats are emitted every 10 s and visible
via `GET /api/agents/health`.

| Agent | File | Responsibility | Subscribes to | Emits |
|---|---|---|---|---|
| `MarketIntelAgent` | `market_intel.py` | Ingest market data (ticks, OHLCV) from Yahoo / backtest providers; broadcast to bus | *(none — source of truth)* | `Tick`, `OHLCV` |
| `RegimeAgent` | `regime.py` | Classify market regime (trending_up, trending_down, mean_reverting, high_volatility) from OHLCV | `OHLCV` | `RegimeBroadcast` |
| `StrategyGenAgent` | `strategy_gen.py` | Evaluate active strategy set per bar, emit weighted signals | `OHLCV`, `RegimeBroadcast` | `Signal` |
| `RiskManagementAgent` | `risk_mgmt.py` | Pre-trade risk: max position, drawdown, leverage, kill-switch veto | `Signal`, `Order`, `Fill` | `RiskCheck`, `KillSwitch` |
| `ExecutionAgent` | `execution.py` | Order routing to broker (paper) or paper fill simulator; idempotent order IDs | `Signal` (vetted by risk), `Order` | `Order`, `Fill` |
| `PortfolioAgent` | `portfolio.py` | Position tracking, mark-to-market, PnL aggregation | `Fill`, `OHLCV` | `Portfolio`, `PnL` |
| `ReconciliationAgent` | `reconciliation.py` | Cross-check internal positions vs broker positions; surface drift | `Fill` | `ReconciliationReport` (Wave 7: full impl) |
| `ReflectionEngine` | `reflection_engine.py` | Propose strategy mutations (weight changes, parameter sweeps) gated behind `TRA_REFLECTION_MUTATION_ENABLED` (off by default) | `PnL`, `ReconciliationReport` | `StrategyMutationProposal` |
| `PersonasAgent` | `personas.py` | Simulated operator-persona decisioning (testing/dry-run) | `Signal` | `Signal` (annotated) |
| `AlertAgent` | `alert.py` | Threshold/rate-limited alerts to Telegram + log | `KillSwitch`, `RiskCheck` (severity ≥ warn) | *(none — terminal)* |
| *(orchestrator)* | `system.py` | `TradingSystem` is **not** an agent — wires agents together, exposes HTTP endpoints | — | — |

## Strategies (`src/strategies/`)

14 strategies total, governed by `src/config/strategy_config.py`.
Only **3 are active** in the current paper run; **2 are filters**
(weight 0, block signals when condition fails); **9 are disabled**
in `__init__.py` `ignore_list`. See
[`active_strategy_set.md`](active_strategy_set.md) for cold-start
math and filter behavior.

### Active (vote on signals)
| Strategy | File | Type | Weight | Cold-start |
|---|---|---|---|---|
| `momentum` | `tsmom.py` | Trend | 0.40 | 20 candles (~20 min) |
| `sideways_reversion` | `sideways_reversion.py` | Reversion | 0.35 | 20 candles |
| `vwap_reversion` | `vwap_reversion.py` | Reversion | 0.25 | 20 candles |

### Filters (weight 0; block when condition fails)
| Filter | File | Cold-start |
|---|---|---|
| `ema200_regime_gate` | `ema_regime.py` | 200 candles (~3.3 h) |
| `adx_regime_filter` | `adx_filter.py` | 14 candles (~15 min) |

### Disabled (in `__init__.py` `ignore_list`)
- `pca_statarb` — `pca_statarb.py` (planned re-activation in Wave 7 / Task 48 with proper pair selection)
- `ml_regime` — `ml_regime.py`
- `stat_arb` — `stat_arb.py` (planned re-activation in Wave 7 / Task 48)
- `microstructure` — `microstructure.py` (Wave 8 / Task 53 will wire order-flow imbalance)
- `volatility_compression` — `volatility_compression.py`
- `vol_breakout` — `vol_breakout.py`
- `opening_range_breakout` — `opening_range_breakout.py`
- `technical` — `technical.py` (legacy generic indicator stack)
- `base` — `base.py` (abstract; not a strategy)

## Event types (`src/schemas/events.py`)

All inter-agent communication uses Pydantic-typed events. Events
are **append-only** and **immutable**; agents emit new events
rather than mutating shared state.

| Event | Channel prefix | Emitted by | Consumed by | Lifecycle |
|---|---|---|---|---|
| `Tick` | `market.tick` | MarketIntel | (cache only — not stored) | ephemeral |
| `OHLCV` | `market.ohlcv` | MarketIntel | StrategyGen, Regime, Portfolio | persisted, replayable |
| `RegimeBroadcast` | `system.regime` | Regime | StrategyGen (weight scaling) | persisted |
| `Signal` | `signal.*` | StrategyGen | RiskMgmt, Personas | persisted |
| `RiskCheck` | `risk.check` | RiskMgmt | Alert, dashboard | persisted (audit) |
| `Order` | `order.*` | Execution (post-veto) | RiskMgmt, broker, Portfolio | persisted, state-machine |
| `Fill` | `order.fill` | Broker (or paper) | Portfolio, Reconciliation, Attribution | persisted |
| `Portfolio` | `portfolio.*` | Portfolio | Reconciliation, dashboard | persisted |
| `PnL` | `portfolio.pnl` | Portfolio | ReflectionEngine, dashboard | persisted |
| `KillSwitch` | `risk.kill_switch` | RiskMgmt (or HTTP) | Execution (veto), Alert, dashboard | persisted (high pri) |
| `ReconciliationReport` | `risk.reconciliation` | Reconciliation | ReflectionEngine, dashboard | persisted |
| `StrategyMutationProposal` | `system.mutation` | ReflectionEngine | (human review — never auto-applied) | persisted, draft |
| `Heartbeat` | `system.heartbeat` | All agents | `system.py` liveness | ephemeral (10 s interval) |

Order state machine:
```
NEW → SUBMITTED → ACCEPTED → PARTIALLY_FILLED → FILLED
                 ↓
                 REJECTED
                 CANCELLED
                 EXPIRED
```
Order state transitions are written to the event store so that
restart recovery can rebuild in-flight order status deterministically.

## Storage backends (`src/event_store/`)

The event store is **pluggable** via `TRA_EVENT_STORE_TYPE`:

| Backend | When to use | Pros | Cons |
|---|---|---|---|
| `SqliteEventStore` (`sqlite.py`) | **Default** — local dev, single-process paper run | Zero deps, WAL mode supports concurrent readers, durable | Single writer at a time; not horizontally scalable |
| `PostgresEventStore` (`postgres.py`) | Production (Railway, multi-agent) | Real concurrent readers, TimescaleDB hypertable for OHLCV analytics | Requires `asyncpg` + Postgres URL |
| `KafkaEventStore` (`kafka.py`) | **Forward-compat only** — not in hot path today; planned for Wave 8 (Phase 3) | Durable log, multi-consumer fan-out | Operational overhead, requires Kafka cluster |
| `InMemoryEventStore` (`memory.py`) | Tests only | Fast, deterministic | No durability |

Selection logic at startup (in `event_store/__init__.py`):
```python
if TRA_EVENT_STORE_TYPE == "postgres": PostgresEventStore(...)
elif TRA_EVENT_STORE_TYPE == "kafka":   KafkaEventStore(...)  # not used in hot path
else:                                    SqliteEventStore(...)
```

## Broker connectors (`src/connectors/`)

Five broker / data connectors ship today, but **only the paper
simulator is in the live hot path** during the burn-in. Live broker
routing is not yet enabled (`TRA_LIVE_TRADING_ENABLED=false`).

| Connector | Path | Purpose | Hot path? |
|---|---|---|---|
| **Yahoo Finance** | `yahoo.py` | Historical OHLCV (free fallback) | **Yes** (paper) |
| **Backtest provider** | `backtest_provider.py` | Historical replay data | **Yes** (backtest) |
| **Alternative data** | `alternative_data.py` | RSS / news sentiment + earnings calendar | **Yes** (regime signal) |
| **Kite (Zerodha)** | `kite/{client,broker,market_data}.py` | Live NSE order routing + market data | Stub (auth wired, not enabled) |
| **Angel** | `angel/{client,market_data,symbol_index,websocket}.py` | Live NSE order routing + WS market data | Stub (auth wired, not enabled) |
| **Groww** | `groww/{client,market_data}.py` | Live NSE order routing + market data | Stub (auth wired, not enabled) |
| **Jugaad-data** | `jugaad/{client,market_data}.py` | Free historical NSE data | Used by backtest |

> The previous plan claimed "5 broker connectors" — there are
> actually **7**: 4 live-routing brokers (Kite, Angel, Groww, paper
> simulator) and 3 data providers (Yahoo, backtest, jugaad). The
> paper run uses Yahoo + backtest.

### Broker selection logic
`src/connectors/__init__.py` selects the broker at startup based
on env vars. Order of precedence (highest first):
1. **Paper simulator** (default) — `TRA_PAPER_TRADING=true` (set
   during burn-in)
2. **Kite** — `TRA_KITE_API_KEY` + `TRA_KITE_ACCESS_TOKEN` set
3. **Angel** — `TRA_ANGEL_*` set
4. **Groww** — `TRA_GROWW_API_KEY` + `TRA_GROWW_API_SECRET` +
   `TRA_GROWW_TOTP_SECRET` set

Live broker routing is **gated** behind
`TRA_LIVE_TRADING_ENABLED=true`, which the burn-in does **not**
set. To promote to live, see
[`live_trading_gate.md`](live_trading_gate.md).

## State persistence

| State | Lives in | Persisted across restart? |
|---|---|---|
| Event log (full audit trail) | `state/trading_events.db` (SQLite) or Postgres `events` hypertable | **Yes** (durable) |
| Order state machine | `state/order_state.db` | **Yes** (durable) |
| Open positions | Derived from `Fill` events on startup; cached in `PortfolioAgent` memory | **Yes** (rebuilt from events) |
| Risk limits | `src/risk/position_registry.py` (in-process) | No — reset on restart (by design; limits are static config) |
| Kill-switch state | `src/risk/kill_switch.py` (in-process) | **No** — reset on restart (see Task 30 for persistence refactor) |
| Strategy parameters | `src/config/strategy_config.py` (code) | Yes (code = config) |
| Strategy mutation proposals | Event log (proposals, never auto-applied) | **Yes** (audit trail) |
| Symbol universe (Angel) | `state/angel_symbols.json` (26 MB cache) | **Yes** (cached; TTL Wave 4 Task 26) |
| Metrics | `src/monitoring/metrics.py` (in-process) | **No** — wiped on restart (Wave 4 Task 21 will persist) |
| Live PnL snapshot | Derived from `Fill` + latest `OHLCV` | **Yes** (rebuilt) |

## Risk layer (`src/risk/`)

8 risk modules; the agent layer (above) wraps these as
`RiskManagementAgent`.

| Module | Purpose |
|---|---|
| `kill_switch.py` | Drawdown + daily-loss trip; singleton antipattern (Task 30 will refactor to lazy-lock init) |
| `position_registry.py` | Per-symbol position + exposure tracking |
| `reconciliation.py` | Cross-check internal vs broker state |
| `portfolio_optimizer.py` | HRP (hierarchical risk parity) allocation |
| `kelly_sizing.py` | Kelly / fractional-Kelly sizing (Wave 8 Task 54) |
| `earnings_filter.py` | Block signals on result-day ±1 (Wave 7 Task 46) |
| `analytics.py` | Sharpe, Sortino, max DD, exposure aggregation |
| `costs.py` | Transaction-cost model (brokerage, STT, GST, slippage) |

## Observability (`src/monitoring/`)

7 monitoring modules. The **only durable** path is the event log
itself; metrics are ephemeral by design (Wave 4 Task 21 will add
SQLite-backed metrics).

| Module | Purpose | Hot path? |
|---|---|---|
| `metrics.py` | Prometheus text exporter on `:8080/metrics` | **Yes** (lightweight counters) |
| `http_dashboard.py` | HTML dashboard served from `:8080/` | **Yes** (read-only) |
| `dashboard.py` | Rich-CLI dashboard for terminal | No (interactive only) |
| `latency_tracer.py` | Per-event latency timing | **Yes** |
| `attribution.py` | Per-strategy PnL attribution | **Yes** (writes to event log) |
| `burnin.py` | Paper-burn-in gate scoring | **Yes** (paper run) |
| `decay_detector.py` | Strategy performance-decay detection | **Yes** (background) |

3 Prometheus alerts exist today (`prometheus_alerts.yml`); Wave 4
Task 25 will grow this to 10+.

## Dashboard (`dashboard/`)

- **Backend**: `dashboard/server.py` — FastAPI on port 8080
- **Auth**: Bearer token in `Authorization: Bearer <TRA_HTTP_AUTH_TOKEN>`
  header on all `/api/control/*` endpoints (kill switch, position
  flatten, regime override, dry-run toggle)
- **Frontend**: `dashboard/src/` — React + TypeScript + Vite
- **Built artifact**: `dashboard/dist/` (gitignored)
- **Endpoints**:
  - `GET /metrics` — Prometheus text
  - `GET /api/agents/health` — per-agent heartbeat
  - `GET /api/portfolio` — positions, PnL
  - `POST /api/control/kill-switch/reset` — clear kill switch (auth required)
  - `GET /api/output/validation_report` — backtest validation results
    (currently placeholder; Wave 4 Task 27 will wire to real data)

## Configuration (`src/config/`)

- `settings.py` — Pydantic-Settings; reads `TRA_*` env vars
- `strategy_config.py` — active strategy set + weights
- All secrets flow through `src/utils/vault.py` (env → file → AWS
  Secrets Manager / HashiCorp Vault via `[vault]` extra)

## What is *not* in the architecture

To pre-empt common questions:

- **No Rust / Go code.** The previous `init.md` claimed a Rust
  engine and Go routing layer; neither was built.
- **No Kafka in the hot path.** `aiokafka` is installed for the
  optional `KafkaEventStore` (forward-compat), but the paper run
  uses SQLite or Postgres.
- **No Flink / Spark.** No stream-processing layer.
- **No Kubernetes.** Deployment target is Railway (single
  container). No Helm charts, no Terraform, no Istio.
- **No live broker routing yet.** All order flow in the burn-in
  is paper-simulated by `ExecutionAgent` itself.

For the timeline of how we got here, see
[`plan.md`](../plan.md) and
[`trading_engine_audit_2026-06-02.md`](trading_engine_audit_2026-06-02.md).
