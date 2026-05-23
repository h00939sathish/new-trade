# Trading System — Master Plan

## Vision
Institutional-grade multi-agent AI trading system. Multi-asset (equities, futures, forex, crypto), multi-timeframe, event-driven, cloud-native, fault-tolerant, observable.

## Architecture

### Five Active Agents

| Agent | Role | Status |
|-------|------|--------|
| Market Intelligence | Ingest market data, compute features | Built |
| Strategy Generation | Generate/select trading signals | Built |
| Risk Management | Validate orders pre/post-trade, VaR, exposure | Built |
| Execution | Route/execute orders, smart routing | Built |
| Portfolio Optimization | Allocate capital, rebalance | Phase 3 |

### Event-Driven Data Flow
```
Market Feeds → MarketIntel → StrategyGen → RiskMgmt → Execution → Order/Fill
                                                    ↑              ↓
                                              Portfolio ←──── Feedback Loop
```

### Communication
- **Primary**: SQLite event store (dev), PostgreSQL/TimescaleDB (prod) via unified EventStore interface
- **Bus**: Single `events.bus` stream with per-agent subscription filtering by EventType
- **Live data**: Groww REST polling (free), Kite WebSocket (₹500/mo Connect plan)

### Infrastructure Stack

| Layer | Dev | Production |
|-------|-----|-----------|
| Event Store | SQLite | PostgreSQL + TimescaleDB |
| Runtime | Python asyncio | Python asyncio + Docker Compose |
| Monitoring | agent health() endpoint | Prometheus + Grafana |
| Backtesting | In-memory replay | Historical DB + sandbox |

---

## Implementation Phases

### Phase 1 — Foundation ✅ (COMPLETE)

Goal: Core event-driven pipeline with 4 agents working end-to-end.

- [x] Set up project structure (src/agents, src/schemas, src/event_store, src/connectors)
- [x] Event store interface + SQLite/InMemory/Postgres/Kafka implementations
- [x] Base agent with event bus loop, subscriptions, lifecycle
- [x] MarketIntelAgent — ingest ticks/OHLCV via inject_* or live provider
- [x] StrategyGenAgent — Momentum + MeanReversion strategies with signal emission
- [x] RiskManagementAgent — pre-trade signal/order validation with configurable limits
- [x] ExecutionAgent — paper trading (simulated fills) + broker integration
- [x] TradingSystem — orchestration, lifecycle, health endpoint
- [x] 37 unit + integration tests passing
- [x] Exchange field flows through Tick → Signal → Order events (bug fix)

### Phase 2 — Live Data & Execution 🟡 (IN PROGRESS)

Goal: Connect to real broker APIs for live market data and order execution.

- [x] Kite/Zerodha login: access_token exchanged, profile verified
- [x] Groww connector: REST client with LTP/quote/OHLC/historical endpoints
- [x] GrowwMarketDataProvider: polling-based, matches KiteMarketDataProvider interface
- [x] KiteBroker: order placement via Kite API
- [ ] **Groww provider async**: migrate `requests` → `httpx` async client
- [ ] **Groww OHLCV polling**: `_poll_loop` calls `_on_ohlcv` callback (currently only ticks)
- [ ] **Groww token auto-refresh**: detect 401, retry via TOTP, update env
- [ ] **Wire OHLCV historical data**: `MarketIntelAgent.on_start` loads recent candles
- [ ] **End-to-end broker test**: place real order via KiteBroker → verify fills
- [ ] **Clean up debug logging**: remove `logger.debug()` noise from strategy_gen, base, store

### Phase 3 — Intelligence & Risk

Goal: Expand strategy library, add portfolio optimization, enhance risk framework.

- [ ] **Additional strategies**: ATR (volatility-based), Bollinger Bands (mean-reversion + breakout), RSI (overbought/oversold), MACD (trend-following)
- [ ] **Strategy registry**: named strategies with configurable params, enable/disable per instrument
- [ ] **PortfolioOptimizationAgent**: Kelly Criterion position sizing, rebalancing
- [ ] **Enhanced risk**: VaR (daily 95%/99%), correlation matrix, concentrated position limits
- [ ] **Backtesting module**: replay historical events through current agent pipeline, compute P&L
- [ ] **Strategy sandbox**: run strategies in isolation before committing capital
- [ ] **Multi-timeframe support**: aggregate OHLCV across 1m/5m/15m/1D for combined signals

### Phase 4 — Production Readiness

Goal: Deployable system with monitoring, persistence, and operational tooling.

- [ ] **Docker Compose**: app + PostgreSQL + Redis + Grafana stack
- [ ] **PostgreSQL event store**: tested and verified as primary production store
- [ ] **Prometheus metrics**: /metrics endpoint with counters for events/signals/orders
- [ ] **CLI dashboard**: `rich`-based live view of agent health, signals, orders, P&L
- [ ] **Multi-asset support**: NFO (futures/options) + crypto connectors
- [ ] **Graceful shutdown**: signal handling, in-flight order cleanup
- [ ] **Alert system**: email/telegram alerts for risk breaches, system errors

### Phase 5 — ML & Scaling

Goal: Machine learning strategies, distributed execution, full production deployment.

- [ ] **Feature engineering pipeline**: technical indicators → feature vectors
- [ ] **RL training pipeline**: Ray RLlib for multi-agent reinforcement learning
- [ ] **Online learning**: LightGBM model updates from new market data
- [ ] **Kubernetes deployment**: Helm charts, horizontal pod autoscaling
- [ ] **Multi-region DR**: active-active with failover event store
- [ ] **FIX protocol**: direct exchange connectivity for ultra-low-latency execution

## Key Principles
- Event sourcing for full replayability and audit
- Deterministic simulation-to-live parity
- Fail-fast, fail-safe, self-healing
- Defense in depth (risk layers at every stage)
- Observability as a first-class feature
- Async-first, non-blocking I/O throughout

## Risk Framework
1. **Pre-trade validation gate** — position limits, VaR checks, correlation bounds
2. **Real-time risk monitor** — P&L drawdown, volatility regime, exposure tracking
3. **Order-level validation** — size, value, daily limits
4. **Portfolio-level oversight** — concentration, leverage, rebalance triggers

## Build vs Buy Decisions
| Component | Decision | Rationale |
|-----------|----------|-----------|
| Trading Engine | **Custom Python** (asyncio + event store) | Fast iteration, full control, no vendor lock |
| Backtesting | **Custom replay engine** | Uses same event pipeline, sim-to-live parity |
| ML Training | **Ray RLlib** (Phase 5) | Distributed, production-proven, multi-agent |
| Event Bus | **SQLite→PostgreSQL** | Simple, reliable, no Kafka ops overhead for MVP |
| Live Data | **Groww REST API** (free, working) | Kite data costs ₹500/mo |
| Order Execution | **Kite/Zerodha** (free tier) | Orders work on free Personal plan |
