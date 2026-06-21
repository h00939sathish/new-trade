# SYSTEM MAP — Complete Architecture

## 1. REPOSITORY TOPOLOGY

```
new-trade/
├── src/                          # Application source
│   ├── main.py                   # Entrypoint: boot, wire agents, HTTP server
│   ├── system.py                 # TradingSystem: lifecycle orchestrator
│   ├── agents/                   # 11 long-running agents (event-driveen)
│   │   ├── base.py               # BaseAgent: lifecycle, bus subscription, health
│   │   ├── market_intel.py       # MarketIntelAgent: tick/OHLCV ingestion
│   │   ├── regime.py             # RegimeDetectionAgent: market regime classifier
│   │   ├── strategy_gen.py       # StrategyGenAgent: consensus signal engine
│   │   ├── risk_mgmt.py          # RiskManagementAgent: pre-trade risk gate
│   │   ├── execution.py          # ExecutionAgent: order routing, TWAP, fills
│   │   ├── portfolio.py          # PortfolioOptimizationAgent: PnL, positions, optimizer
│   │   ├── reconciliation.py     # ReconciliationAgent: broker vs local drift
│   │   ├── reflection_engine.py  # ReflectionEngineAgent: auto-strategy mutation
│   │   ├── alert.py              # AlertAgent: Telegram/PagerDuty/ntfy/log
│   │   └── personas.py           # PersonasAgent: synthetic operator decisioning
│   ├── config/
│   │   ├── settings.py           # Pydantic-settings (TRA_* env vars)
│   │   └── strategy_config.py    # Strategy registry + YAML loader
│   ├── connectors/               # 7 broker/data connectors
│   │   ├── yahoo.py              # Yahoo Finance (paper hot path)
│   │   ├── backtest_provider.py  # Historical replay (backtest)
│   │   ├── alternative_data.py   # RSS/news/earnings
│   │   ├── kite/                 # Zerodha Kite (live, stub)
│   │   ├── angel/                # Angel Broking (live, stub)
│   │   ├── groww/                # Groww (live, stub)
│   │   └── jugaad/               # Jugaad-data (free NSE historical)
│   ├── core/                     # (unused during paper burn-in)
│   ├── event_store/              # Pluggable event persistence
│   │   ├── base.py               # EventStore ABC
│   │   ├── async_bus.py          # AsyncEventBus: in-process pub/sub (singleton)
│   │   ├── sqlite.py             # SqliteEventStore (default, WAL mode)
│   │   ├── postgres.py           # PostgresEventStore (+TimescaleDB optional)
│   │   ├── kafka.py              # KafkaEventStore (forward-compat, not hot path)
│   │   └── memory.py             # InMemoryEventStore (tests)
│   ├── execution/
│   │   └── hardening.py          # StaleDataWatchdog, DuplicateOrderProtector, etc.
│   ├── monitoring/
│   │   ├── metrics.py            # MetricsCollector: Prometheus counters/gauges
│   │   ├── metrics_store.py      # MetricsStore: SQLite-backed metrics persistence
│   │   ├── http_dashboard.py     # HTML dashboard served from :8080
│   │   ├── dashboard.py          # Rich CLI dashboard
│   │   ├── latency_tracer.py     # Per-event latency timing
│   │   ├── attribution.py        # Per-strategy PnL attribution
│   │   ├── burnin.py             # Paper burn-in reconciliation
│   │   ├── decay_detector.py     # Strategy performance decay detection
│   │   └── strategy_scoreboard.py # Strategy ranking/monitoring
│   ├── risk/
│   │   ├── kill_switch.py        # KillSwitch singleton (drawdown + daily loss)
│   │   ├── position_registry.py  # PositionRegistry singleton (SSOT)
│   │   ├── reconciliation.py     # Broker position reconciliation
│   │   ├── portfolio_optimizer.py # InstitutionalPortfolioOptimizer (Ledoit-Wolf)
│   │   ├── kelly_sizing.py       # Kelly/fractional-Kelly position sizing
│   │   ├── earnings_filter.py    # Earnings calendar blocker
│   │   ├── costs.py              # Transaction cost model
│   │   └── analytics.py          # Sharpe/Sortino/max DD etc.
│   ├── schemas/
│   │   └── events.py             # 17 Pydantic event types, 4 enums
│   ├── strategies/               # 14 strategies (3 active, 2 filters, 9 disabled)
│   │   ├── base.py
│   │   ├── tsmom.py              # Time-series momentum (disabled)
│   │   ├── sideways_reversion.py # Sideways reversion (ACTIVE, weight 0.35)
│   │   ├── vwap_reversion.py     # VWAP reversion (ACTIVE, weight 0.25)
│   │   ├── ema_regime.py         # EMA200 regime gate (FILTER, weight 0.0)
│   │   ├── adx_filter.py         # ADX regime filter (FILTER, weight 0.0)
│   │   ├── momentum.py           # Momentum (ACTIVE, weight 0.40) — file uses class name "momentum"
│   │   ├── pca_statarb.py        # PCA stat arb (disabled)
│   │   ├── stat_arb.py           # Stat arb (disabled)
│   │   ├── microstructure.py     # Order-flow imbalance (disabled)
│   │   ├── volatility_compression.py # (disabled)
│   │   ├── vol_breakout.py       # (disabled)
│   │   ├── opening_range_breakout.py # (disabled)
│   │   └── technical.py          # Legacy generic indicators (disabled)
│   ├── utils/
│   │   ├── vault.py              # HashiCorp Vault + AWS Secrets Manager
│   │   └── timeframe.py          # Candle aggregation utils
│   ├── backtest/
│   │   └── engine.py             # BacktestEngine
│   ├── ml/                       # ML models (regime classifier, etc.)
│   ├── analytics/                # Portfolio analytics
│   ├── research/                 # Research notebooks/scripts
│   ├── validation/               # Validation utilities
│   └── mcp_tools/                # MCP tool definitions
├── dashboard/
│   ├── server.py                 # FastAPI backend (port 8081)
│   ├── src/                      # React + TypeScript + Vite frontend
│   └── dist/                     # Built artifact (gitignored)
├── tests/                        # ~50 test files
│   ├── conftest.py               # Fixtures (isolated metrics store, etc.)
│   ├── test_live_safety.py       # P0 safety tests
│   └── ...
├── config/
│   ├── champions.yaml            # Strategy champion configs
│   ├── candidates/               # Reflection engine candidates
│   └── earnings_calendar.yaml    # Earnings dates
├── docs/
│   ├── ARCHITECTURE.md           # This document (derived from audit)
│   ├── OPERATIONS.md             # Operations runbook
│   ├── RUNBOOK.md                # Incident response
│   ├── live_trading_gate.md      # Prerequisites for live trading
│   ├── active_strategy_set.md    # Strategy cold-start math
│   └── ...
├── scripts/                      # Operations scripts
├── state/                        # Runtime state (gitignored)
│   ├── trading_events.db         # SQLite event store
│   ├── order_state.db            # SQLite order state machine
│   ├── metrics.db                # SQLite metrics store
│   ├── kill_switch.state         # Persisted kill switch state
│   └── burnin/reconciliation.jsonl # Paper burn-in reconciliation log
├── data/                         # Data files
├── reports/                      # Generated reports
├── logs/                         # Runtime logs
├── docker-compose.yml            # Postgres + Redis + Prometheus + Grafana
├── Dockerfile                    # Single-container deployment
├── prometheus.yml                # Prometheus scrape config
├── prometheus_alerts.yml         # 3 alert rules
├── CHANGELOG.md
├── SECURITY.md
├── Makefile
└── pyproject.toml                # Dependencies, lint, test config
```

## 2. RUNTIME FLOW

### 2.1 Data Path (Paper Trading)
```
Yahoo Finance / Backtest Provider
    │
    ▼
MarketIntelAgent.on_start()
    │  subscribes to market_data_provider callbacks
    │  _on_provider_tick() → ingest_tick() → emit(TickEvent)
    │  _on_provider_ohlcv() → ingest_ohlcv() → emit(OHLCVEvent)
    ▼
AsyncEventBus.publish(event)
    │  fan-out to all subscribed agent queues (maxsize=100k)
    │  background persist to SqliteEventStore
    ▼
StrategyGenAgent._process_tick() / _process_ohlcv()
    │  store in _tick_prices / _candle_prices deques (maxlen=500)
    │  evaluate all strategies → weighted votes → consensus
    │  check regime stability, dedup, cooldown
    │  if abs_net >= threshold → emit(SignalEvent)
    ▼
RiskManagementAgent._validate_signal()
    │  9+ risk checks: market hours, square-off, drawdown, VaR,
    │  liquidity, per-trade, max positions, earnings, correlation,
    │  trend alignment, exposure
    │  emit(RiskCheckEvent) with passed=True/False
    ▼
ExecutionAgent._handle_risk_check()
    │  if passed: _execute_approved_signal()
    │    calculate quantity (Kelly/ATR/HRP)
    │    if >=500: _start_twap() with 30s intervals
    │    else: OrderEvent.create() → emit(ORDER_PROPOSED)
    │    → RiskManagementAgent._validate_order()
    │    → emit(RiskCheckEvent) → _submit_approved_order()
    │      → broker.place_order() or _simulate_fill()
    ▼
PortfolioOptimizationAgent._on_fill()
    │  update PositionRegistry (SSOT)
    │  calculate PnL, track strategy returns
    │  run InstitutionalPortfolioOptimizer every 300s
    │  emit(PortfolioEvent)
    ▼
ReconciliationAgent._check_drift()
    │  compare PositionRegistry vs PortfolioAgent quantities
    │  emit RISK_BREACH on mismatch
```

### 2.2 Kill Switch Flow
```
Trigger conditions:
  1. Daily PnL < -max_daily_loss  (initial_capital * daily_loss_pct)
  2. Drawdown > max_drawdown_pct

KillSwitch.trigger():
  1. Set _active = True, persist state
  2. Disable strategy_gen._running
  3. Emit SYSTEM_ERROR (fatal)
  4. Cancel all open orders via exec_agent.cancel_order()
  5. Market-close all positions

Auto-reset (next trading day):
  daily_auto_reset() checks trigger_date < today → clear state
```

### 2.3 Order State Machine
```
NEW (SignalEvent)
  → ORDER_PROPOSED (emitted by ExecutionAgent)
    → RiskManagementAgent._validate_order()
      → RiskCheckEvent (passed/failed)
        → ORDER_CREATED (if passed)
          → PENDING
            → ACCEPTED | REJECTED | CANCELLED
              → PARTIALLY_FILLED → FILLED
```

## 3. DEPLOYMENT TOPOLOGY

### Current (Paper Burn-in)
```
Single process (Python 3.12)
    │
    ├── asyncio event loop
    │   ├── 11 agent tasks (bus subscription loops)
    │   ├── TWAP loop
    │   ├── Reconciliation loop
    │   ├── Metrics HTTP server (:8080)
    │   ├── WebSocket connections (Angel/Yahoo)
    │   └── CLI dashboard
    │
    ├── SQLite (state/trading_events.db)
    ├── SQLite (state/order_state.db)
    ├── SQLite (state/metrics.db)
    └── File (state/kill_switch.state)
```

### Docker Compose (Production target)
```
┌─────────────┐  ┌──────────┐  ┌───────────┐  ┌────────┐
│ trading-app │  │ Postgres │  │  Redis    │  │Prometheus│
│ (container) │──│(Timescale│  │(unused in │  │ scrape  │
│             │  │   DB)    │  │ hot path) │  │ :9090   │
└─────────────┘  └──────────┘  └───────────┘  └────┬───┘
                                                   │
                                              ┌────▼───┐
                                              │ Grafana│
                                              │ :3000  │
                                              └────────┘
```

## 4. EVENT TYPES (17 total)

| EventType | Value | Producer | Consumers | Persisted |
|-----------|-------|----------|-----------|-----------|
| TICK | market.tick | MarketIntel | Execution, Portfolio | No (ephemeral) |
| OHLCV | market.ohlcv | MarketIntel | StrategyGen, Regime, Portfolio | Yes |
| SIGNAL | signal.generated | StrategyGen | RiskMgmt, Personas | Yes |
| CANDIDATE_SIGNAL | signal.candidate | StrategyGen | ReflectionEngine | Yes |
| ORDER_PROPOSED | order.proposed | Execution | RiskMgmt | Yes |
| ORDER_CREATED | order.created | Execution | RiskMgmt, Portfolio, Alert | Yes |
| ORDER_ACCEPTED | order.accepted | Broker | Execution | Yes |
| ORDER_REJECTED | order.rejected | Broker/Execution | All | Yes |
| ORDER_CANCELLED | order.cancelled | Execution/User | All | Yes |
| FILL | order.fill | Broker/Paper | Portfolio, Recon, Attribution | Yes |
| RISK_CHECK | risk.check | RiskMgmt | Execution, Alert | Yes |
| RISK_BREACH | risk.breach | RiskMgmt | Alert, dashboard | Yes |
| PORTFOLIO_UPDATE | portfolio.update | PortfolioOpt | RiskMgmt, Execution | Yes |
| PORTFOLIO_REBALANCE | portfolio.rebalance | PortfolioOpt | — | Yes |
| POSITION_UPDATE | position.update | PortfolioOpt | — | Yes |
| PNL_UPDATE | pnl.update | Attribution | ReflectionEngine | Yes |
| SYSTEM_HEALTH | system.health | All agents | system.py | No (ephemeral) |
| SYSTEM_ERROR | system.error | KillSwitch/Agents | Alert, dashboard | Yes |
| SYSTEM_STATE | system.state | Regime | StrategyGen | Yes |
| AGENT_STATUS | agent.status | Agents | — | Yes |
| MACRO_SENTIMENT | macro.sentiment | Personas | StrategyGen | Yes |
| STRATEGY_DECAY | strategy.decay | DecayDetector | ReflectionEngine | Yes |

## 5. RISK MODULES (8)

| Module | Type | Applies | Latency |
|--------|------|---------|---------|
| KillSwitch | Global | Pre/Post-trade | < 1ms |
| PositionRegistry | Per-symbol | Post-trade | < 1ms |
| TransactionCostModel | Per-order | Post-fill | < 1ms |
| EarningsCalendarFilter | Per-symbol | Pre-signal | < 1ms |
| KellySizer | Per-strategy | Pre-execution | < 50ms (SQLite) |
| InstitutionalPortfolioOptimizer | Portfolio | Every 300s | 50-200ms (scipy) |
| Reconciliation | Broker vs Local | Every 300s | Variable (network) |
| Analytics | Portfolio | On demand | Variable |

## 6. CONFIGURATION (TRA_* env vars)

37 settings via Pydantic-Settings. Key categories:
- **Event store**: TRA_EVENT_STORE_TYPE, TRA_POSTGRES_DSN
- **Broker credentials**: TRA_KITE_*, TRA_ANGEL_*, TRA_GROWW_*
- **Risk limits**: TRA_RISK_MAX_POSITION_SIZE, MAX_DRAWDOWN_PCT, MAX_LEVERAGE, etc.
- **Kill switch**: TRA_KILL_SWITCH_DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT, AUTO_RESET
- **Live trading gate**: TRA_LIVE_TRADING_ENABLED (default: False)
- **Agent toggles**: TRA_AGENT_MARKET_INTEL_ENABLED, etc.
- **Sizing**: TRA_RISK_SIZING_METHOD (fixed/kelly)
- **Alerts**: TRA_TELEGRAM_*, TRA_PAGERDUTY_*, TRA_NTFY_*

## 7. DEPENDENCIES

- Python ≥ 3.12, pydantic, pydantic-settings
- pandas, numpy, scipy (optimization)
- asyncpg (Postgres), aiosqlite, aiokafka (forward-compat)
- redis (unused in hot path today)
- httpx, websocket-client (broker connectivity)
- pyyaml, pyotp, jugaad-data
- rich (CLI dashboard)
- duckdb, pyarrow, openbb (data analysis)
- Optional: fastapi/uvicorn (dashboard), scikit-learn/lightgbm/torch (ML)

## 8. CRITICAL SINGLETONS

| Singleton | File | Purpose | Locking |
|-----------|------|---------|---------|
| AsyncEventBus | event_store/async_bus.py | In-process pub/sub | None (coroutine-safe) |
| KillSwitch | risk/kill_switch.py | Global trading halt | asyncio.Lock per check |
| PositionRegistry | risk/position_registry.py | SSOT for positions | asyncio.Lock + threading.RLock |
| MetricsCollector | monitoring/metrics.py | Prometheus counters | None (sync, thread-safe by design) |
