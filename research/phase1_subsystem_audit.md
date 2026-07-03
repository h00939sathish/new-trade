# Phase 1: Full Subsystem Audit

**Evidence Quality Ladder: A=direct code/runtime, B=documented, C=external, D=speculative**

---

## 1. Event Bus & Messaging Layer

### AsyncEventBus (`src/event_store/async_bus.py:17-136`)
- **Singleton pattern**, 5 priority queues (CRITICAL→DEBUG)
- Backpressure via `_backpressure_threshold=500` → drops lowest-priority events
- **Tier A**: CRITICAL events bypass backpressure entirely (`if et.priority is EventPriority.CRITICAL: ...`)
- **Tier A**: Priority reaper thread evicts stale events from low-priority queues
- **Tier A**: 26 event types defined in `src/schemas/events.py:9-34`
- **Tier A**: No event deduplication mechanism — same tick could trigger duplicate signals

### SyncEventBus (`src/backtest/sync_bus.py:10-103`)
- **Tier A**: Drop-in replacement for backtesting — synchronous delivery, no queues
- **Tier A**: Nested event deferral (FIX S2.1 documented in code) fixes the "0 fills" backtest bug
- **Tier A**: Self-emitted event skip (`if event.metadata.producer == agent.name: continue`)
- **Tier A**: No ordering guarantees for events with same producer — race conditions possible

### InMemoryEventStore (`src/event_store/memory.py`)
- Append-only log for testing — no persistence, no replay

**Findings:**
1. [A] Backpressure drops events silently — no audit trail of dropped events
2. [A] No event deduplication — duplicate ticks produce duplicate signals
3. [A] SyncEventBus nested deferral is correct but untested at >2 levels of nesting

---

## 2. Strategy Engine (`src/agents/strategy_gen.py`)

### Signal Pipeline
- **Tier A**: 14 strategies in `STRATEGY_REGISTRY` (see Phase 0 ledger)
- **Tier A**: **3 ACTIVE**: momentum, sideways_regime, vwap_breakout
- **Tier A**: **2 filter strategies**: market_regime_filter, volatility_filter
- **Tier A**: **9 DISABLED** (config `enabled: false`): mean_reversion, rsi, breakout, stat_arb, pairs, ml_signal, options_spread, ict, fundamental
- **Tier A**: Signal consensus in `_publish_signals()`: threshold gate (≥50% active), cooldown (configurable seconds), weight-normalized vote
- **Tier A**: Cooldown enforcement via `_last_signal_time` dict
- **Tier A**: max_trades_per_bar=2 hard limit in `_execute_approved_signal`

### Runtime Divergence: stat_arb ACTIVE
- **Tier A**: `src/config/strategy_config.py:98` has `"enabled": true, "weight": 0.15` for stat_arb
- **Tier A**: Confirmed at runtime (divergence #1 from Phase 0B)
- Root cause: config says enabled:true, docs say disabled

### Strategy Weights
- **Tier A**: Config weights: momentum=0.40, sideways=0.35, vwap=0.25, stat_arb=0.15
- **Tier A**: Runtime weights diverge because regime normalization includes stat_arb's 0.15
- Effective runtime: momentum=0.22, sideways=0.39, vwap=0.28 (divergence #4)

**Findings:**
1. [A] stat_arb active despite documentation claiming disabled — config mismatch
2. [A] Strategy weight normalization includes disabled strategies — weight values are misleading
3. [A] Filter strategies consume signal budget but don't produce tradeable signals — reducing effective capacity
4. [A] No strategy-level performance tracking to auto-disable decaying strategies
5. [A] Cooldown is per-strategy but consensus resets globally

---

## 3. Execution Agent (`src/agents/execution.py`)

### Paper Fill Model (`1249-1311`)
- Depth-aware fill simulation: bid/ask from l1_data or midpoint±0.05%
- Full cost deduction: STT (0.025% sell), GST (18% on brokerage), SEBI (0.0001%), stamp duty (0.015% buy), brokerage (0.03% or ₹20)
- **Tier A**: 5bps default slippage, configurable via settings
- **Tier A**: 50-150ms random latency added per order
- **Tier A**: Execution reports (FILL, REJECTED, CANCELLED) emitted

### Missing in Paper Model
- **No partial fills** — fills are always full quantity or rejected
- **No reject simulation** — rejects only happen for stale TWAP orders or missing symbols
- **No market impact** — fills don't move the price
- **No exchange latency patterns** — uniform random 50-150ms is unrealistic

### TWAP Order State
- **Tier A**: SQLite persistence via `state/order_state.db`
- **Tier A**: Stale orders survive process restart (divergence #2)
- 13 stale orders from previous session generate REJECTED events on startup

### Live Broker Integration
- **Tier A**: KiteBroker wraps kiteconnect synchronously via `asyncio.to_thread`
- **Tier A**: Angel client handles auth, token refresh, symbol resolution
- **Tier A**: `_broker` is None in paper mode — means `reconcile_positions` is a no-op

**Findings:**
1. [A] Stale TWAP orders persist across restarts — causes noise events every startup
2. [A] Paper fill model lacks partial fills — unrealistic for slippage analysis
3. [A] No market impact in paper fills — important for large orders
4. [A] Exchange latency modeled as uniform random — doesn't capture NSE burst patterns

---

## 4. Risk Management Agent (`src/agents/risk_mgmt.py`)

### Risk Checks Pipeline
- **Tier A**: Sequential chain: VaR → margin → concentration → max_position → max_capital → circuit_breaker → kill_switch
- **Tier A**: First failure short-circuits — no further checks run
- **Tier A**: RiskCheckEvent emitted with passed=False + reason

### VaR (`src/risk/var.py:6-53`)
- **Tier A**: Historical VaR(95%) on rolling price history (min 20 returns)
- **Tier A**: Configurable `TRA_RISK_MAX_VAR_PER_SYMBOL` (default 5% of capital)
- **Tier A**: Always returns `passed: True` when data insufficient — gap in protection
- **Tier A**: Simple historical method — no EWMA, no GARCH, no regime-aware VaR

### Margin (`src/risk/margin.py:9-60`)
- **Tier A**: Hardcoded NSE margin rates: MIS=20%, CNC=100%, CO=8%
- **Tier A**: `check_order` accepts buffer_pct for safety margin
- **Tier A**: No SPAN margin calculation — simplified flat percentage

### Market Impact (`src/risk/market_impact.py:4-43`)
- **Tier A**: Almgren-Chriss square-root model with configurable alpha
- **Tier A**: `is_significant` with 20bps default threshold
- **Tier A**: Not wired into execution — advisory only, no position sizing integration

### Position Registry (`src/risk/position_registry.py`)
- **Tier A**: Thread-safe singleton via `threading.Lock`
- **Tier A**: `sync_from_portfolio` method for reconciliation
- **Tier A**: No position-level PnL tracking — just qty/avg_cost

### Reconciliation (`src/risk/reconciliation.py:8-95`)
- **Tier A**: Broker → local position comparison
- **Tier A**: Emits RiskCheckEvent + auto-corrects local positions
- **Tier A**: Only runs when `exec_agent._broker` exists (paper mode skips)
- **Tier A**: FIFO assumption for cost basis

### Kill Switch (`src/risk/kill_switch.py:13-190`)
- **Tier A**: File-persisted to `state/kill_switch.state` (CORRECTION: not ephemeral)
- **Tier A**: Requires manual rearm after trigger
- **Tier A**: Multi-channel triggers: manual, drawdown, error rate, var
- **Tier A**: Railway ephemeral FS would lose state on deploy — contradiction

### NSE Lot Sizes (`src/risk/nse_lot_sizes.py:14-71`)
- **Tier A**: 54 F&O instruments with lot sizes and tick values
- **Tier A**: Includes expiry dates — hardcoded, not updated dynamically
- **Tier A**: Only covers F&O — no cash market lot size reference

**Findings:**
1. [A] VaR returns `passed: True` when data insufficient — false sense of safety
2. [A] VaR is simple historical method — no regime adaptation
3. [A] Market impact model is advisory only — not integrated with position sizing
4. [A] Kill switch persisted to local file — lost on Railway deploy
5. [A] NSE lot sizes are hardcoded with expiry dates — stale within months
6. [A] Risk check short-circuits on first failure — hidden correlated failures

---

## 5. Backtest Engine (`src/backtest/engine.py`)

### Architecture
- **Tier A**: Uses same agents (StrategyGen, RiskMgmt, Execution) with InMemoryEventStore
- **Tier A**: `run_background_loop=False` prevents background tasks
- **Tier A**: Manual tick feed via `engine.run(ticks)` — no time synchronization
- **Tier A**: `position_registry.reset()` for isolation between runs
- **Tier A**: Commission: 0.03%, Slippage: 5bps (default)

### Limitations
- **Tier A**: Uses paper fill model — not historical price + spread data
- **Tier A**: No short-selling support
- **Tier A**: Multi-instrument backtests use same timestamp for all instruments — unrealistic
- **Tier A**: No corporate action handling (splits, dividends, buybacks)

### Walk-Forward Validator (`src/backtest/walk_forward.py:30-257`)
- **Tier A**: N-fold rolling window with non-overlapping OOS periods
- **Tier A**: Parameter grids for momentum, mean_reversion, RSI
- **Tier A**: Sharpe-based optimization with min trade guard against degenerate params
- **Tier A**: Equity curve chaining across windows
- **Tier A**: No walk-forward for vwap_breakout or sideways_regime (no grids defined)
- **Tier A**: Uses 60/20 day split — no configurable ratio

### Grid Optimizer (`src/backtest/optimizer.py:33-82`)
- **Tier A**: Brute-force grid search over parameter combinations
- **Tier A**: Configurable metric (default: sharpe_ratio)
- **Tier A**: No statistical significance check on parameter superiority
- **Tier A**: No cross-validation within optimization — overfitting risk

### Data Provider (`src/connectors/backtest_provider.py:22-382`)
- **Tier A**: Multi-source fallback: Provider → Yahoo → Daily candles → Synthetic
- **Tier A**: Caching to `data/historical/{symbol}_{interval}_{days}d.json`
- **Tier A**: Daily candle expansion to ticks uses interpolation + gaussian noise — unrealistic microstructure
- **Tier A**: Synthetic ticks are sine-wave based — not representative

**Findings:**
1. [A] Backtest uses paper fill model, not historical spread data — PnL unrealistic
2. [A] No corporate actions modeled — significant for long-duration backtests
3. [A] Walk-forward only defined for 3 of 14 strategies
4. [A] Grid optimizer has no overfitting protection
5. [A] Synthetic ticks are sine-wave — will produce unrealistic strategy behavior
6. [A] Multi-instrument backtests don't synchronize time properly

---

## 6. Connector Layer (Broker/Market Data)

### Angel One (`src/connectors/angel/`)
- **Tier A**: Full REST client with JWT auth, auto-refresh, retry logic
- **Tier A**: Symbol index cached to `state/angel_symbols.json` with 24h TTL
- **Tier A**: WebSocket client with binary packet parsing (51+ byte protocol)
- **Tier A**: Dual fallback: Angel → Yahoo Finance for LTP
- **Tier A**: Runtime divergence #3: Angel failed for 3/4 symbols at startup
- **Tier A**: `_resolve_public_ip()` hits ifconfig.me on every `_default_headers` call — cached after first call
- **Tier A**: `_resolve_token` does O(n) linear scan over all symbols — slow for large portfolios

### Kite (`src/connectors/kite/`)
- **Tier A**: KiteClient in placeholder mode when credentials missing — returns fake data
- **Tier A**: Wraps synchronous kiteconnect library — no native async
- **Tier A**: KiteBroker translates schema enums to kiteconnect format
- **Tier A**: No WebSocket support — polling only via `_poll_loop`

### Groww (`src/connectors/groww/`)
- **Tier A**: Unused in current system — not wired into startup
- **Tier A**: Token refresh on 401 with TOTP support
- **Tier A**: No known API stability issues noted

### Jugaad (`src/connectors/jugaad/`)
- **Tier A**: NSE bhavcopy-based historical data via `jugaad_data` library
- **Tier A**: LTP falls back to Yahoo Finance
- **Tier A**: Used primarily as fallback for backtest data provider
- **Tier A**: Market hour awareness — only polls during NSE hours (9:15-15:30 IST)
- **Tier A**: OHLCV candle accumulation from ticks

### Yahoo Finance (`src/connectors/yahoo.py`)
- **Tier A**: LTP and historical chart data via query1.finance.yahoo.com
- **Tier A**: Exchange suffix mapping: NSE → .NS, BSE → .BO
- **Tier A**: No authentication — subject to rate limiting
- **Tier A**: Historical 1m data limited to ~30 days

### Alternative Data (`src/connectors/alternative_data.py`)
- **Tier A**: RSS feed parser for Yahoo Finance news headlines
- **Tier A**: Not wired into any agent — unused in signal generation
- **Tier A**: Returns headlines as plain string — no structured sentiment

### Backtest Data Provider (`src/connectors/backtest_provider.py`)
- **Tier A**: Sophisticated fallback chain: provider → cache → Yahoo → daily → synthetic
- **Tier A**: `coverage` check warns but accepts 0% coverage — data quality gap
- **Tier A**: Daily candle expansion to 375 ticks per candle uses gaussian noise on OHLC

**Findings:**
1. [A] Angel symbol resolution is O(n) linear scan — scaling issue at 5000+ symbols
2. [A] Groww not wired into system — dead code
3. [A] Yahoo Finance has no auth — subject to rate limiting, IP blocking
4. [A] Jugaad daily data is EOD (bhavcopy) — no intraday historical
5. [A] Alternative data RSS feed not consumed by any agent
6. [A] Backtest data provider accepts 0% coverage silently
7. [A] Angel public IP resolution hits external API — privacy concern, potential latency

---

## 7. ML Layer (`src/ml/`)

### Meta Labeler (`src/ml/meta_labeler.py:1-75`)
- **Tier A**: Triple Barrier Meta Labeling implementation
- **Tier A**: `apply_meta_labels()` exists with barrier logic (fixed: 2% upper, 1% lower, 5-day max)
- **Tier A**: **NO trained model** — core stub without weights
- **Tier A**: **NO wiring** into any agent or event bus
- **Tier A**: **NO downstream consumer** of meta labels
- **Tier A**: Manual barrier thresholds — not volatility-adjusted
- **Tier A**: `volatility` parameter accepted but not used in barrier calc

**Findings:**
1. [A] Complete stub — no model, no wiring, no consumer
2. [A] Barrier thresholds are hardcoded (2%/1%/5d), not volatility-adjusted
3. [A] No training pipeline, no data ingestion, no inference
4. [A] No test coverage for the meta labeling logic itself

---

## 8. Portfolio & Analytics

### Portfolio (`src/portfolio/`)
- **Tier A**: Only one file: `hrp_allocator.py` — Hierarchical Risk Parity
- **Tier A**: Uses scipy linkage + numpy for clustering
- **Tier A**: Requires ≥10 data points and ≥2 instruments to produce non-trivial allocations
- **Tier A**: Not wired into PortfolioOptimizationAgent

### Attribution (`src/analytics/attribution.py:37-203`)
- **Tier A**: Reads FILL events, computes per-strategy PnL, Sharpe, profit factor, win rate
- **Tier A**: Outputs to `logs/attribution_<date>.jsonl`
- **Tier A**: FIFO PnL approximation for sell fills
- **Tier A**: Read-only over event store — safe for parallel execution

### Strategy Decay Detector (`src/analytics/strategy_decay.py:8-144`)
- **Tier A**: Rolling 30-window Sharpe, Sortino, win rate, expectancy, drawdown
- **Tier A**: Confidence interval comparison against baseline
- **Tier A**: Actions: Alert → Disable → Reduce Position Size
- **Tier A**: **Not wired into any agent** — actions are theoretical, no system integration
- **Tier A**: `record_trade` must be called externally

**Findings:**
1. [A] HRP not wired into portfolio optimization — unused
2. [A] Strategy decay detector has actions defined but no system connection
3. [A] Attribution aggregator uses FIFO approximation — may diverge from actual PnL for frequent trading

---

## 9. Validation Pipeline (`src/validation/`)

### Orchestrator (`src/validation/orchestrator.py:50-275`)
- **Tier A**: Sequential pipeline: Backtest → Walk-Forward → Monte Carlo → Paper Trade
- **Tier A**: Auto-reject thresholds: Sharpe < 1.2, Profit Factor < 1.3, Drawdown > 10%
- **Tier A**: Weighted scoring across stages
- **Tier A**: Reports saved to `reports/validation/{strategy}_{timestamp}.json`

### Auto-Reject Gates
- **Tier A**: Backtest fail → skip all subsequent stages
- **Tier A**: Walk-forward fail → weighted score, no skip
- **Tier A**: Computes metrics even with 0 trades — degenerate case not handled

### Monte Carlo Validator (`src/validation/monte_carlo.py:24-93`)
- **Tier A**: Bootstrap resampling of trade PnLs (default 1000 sims)
- **Tier A**: Returns Sharpe CI, VaR(95%), probability of loss, avg max drawdown
- **Tier A**: Pass criteria: median Sharpe ≥ 0.8 AND probability of loss < 60%
- **Tier A**: Sequential sampling — no temporal structure preserved

**Findings:**
1. [A] Auto-reject at backtest stage means walk-forward/MC never run for failing strats — no insight into WHY they fail
2. [A] Monte Carlo resamples trades independently — destroys autocorrelation
3. [A] Paper trade stage is a no-op — no paper trading orchestration implemented

---

## 10. Monitoring & Observability

### MetricsCollector (`src/monitoring/metrics.py:39-474`)
- **Tier A**: In-memory counters with optional SQLite persistence via MetricsStore
- **Tier A**: Prometheus text endpoint at `:8000/metrics` (from main.py)
- **Tier A**: 1Hz throttle on portfolio gauge writes — prevents hot-loop issues
- **Tier A**: Flush task every 10 seconds to durable store
- **Tier A**: Counter recovery on restart from last 30 days of SQLite data
- **Tier A**: Gauges NOT restored on restart — portfolio agent re-emits on next update
- **Tier A**: Kill switch state and broker connection in Prometheus output

### CLI Dashboard (`src/monitoring/dashboard.py:15-88`)
- **Tier A**: Rich-based terminal UI with live refresh
- **Tier A**: Polls system health function every 2 seconds
- **Tier A**: Shows agent status, system stats

### HTTP Dashboard (`src/monitoring/http_dashboard.py`)
- Simple HTTP server for health status — not analyzed in detail

### Latency Tracer (`src/monitoring/latency_tracer.py:10-41`)
- **Tier A**: JSONL log to `logs/runtime_traces/traces_YYYYMMDD.jsonl`
- **Tier A**: Correlation ID based tracing across components
- **Tier A**: Not wired into system — `record_trace` must be called externally

### Burn-In (`src/monitoring/burnin.py`)
- **Tier A**: Tracks time since deployment, compares against live_trading_gate.md criteria
- **Tier A**: 30-day paper run requirement

**Findings:**
1. [A] Latency tracer not wired — correlation IDs are generated but never consumed
2. [A] Metrics gauge restore gap on restart — first portfolio update could show stale PnL delta
3. [A] Counter reload from SQLite is best-effort with no error reporting

---

## 11. Core / Regime Detection

### Market Regime Detector
- **Tier A**: Uses rolling volatility (20-period) and trend strength
- **Tier A**: Classifies: bullish, bearish, sideways, high_volatility
- **Tier A**: Regime drives strategy selection in StrategyGenAgent
- **Tier A**: Confirmed working at runtime (Phase 0B tick injection test)

### Circuit Breaker (`src/execution/circuit_breaker.py`)
- **Tier A**: Three states: CLOSED, HALF_OPEN, OPEN
- **Tier A**: Trips on consecutive failures or rapid-fire error rate
- **Tier A**: Half-open allows probe orders after cooldown
- **Tier A**: Exposed via Prometheus metric

**Findings:**
1. [A] Regime detection uses only 20-period lookback — may miss macro regime shifts
2. [A] Circuit breaker state is in-memory only — not persisted across restarts

---

## 12. Security (`src/middleware/auth.py`, `src/utils/vault.py`)

### Auth Middleware
- **Tier A**: `src/middleware/auth.py` exists but largely a stub
- **Tier A**: API key validation for web endpoints
- **Tier A**: No role-based access control

### Secrets Management (`src/utils/vault.py`)
- **Tier A**: Credentials loaded from environment variables (`settings.py:1-180`)
- **Tier A**: TOTP secrets for Angel/Groww stored in env vars — in plaintext
- **Tier A**: No encryption at rest for secrets
- **Tier A**: Paper mode gracefully degrades when credentials missing
- **Tier A**: API keys potentially visible in process listing

### Vault Service (`src/config/settings.py`)
- **Tier A**: 27+ TRA_* env variables define all configuration
- **Tier A**: env_file support for local development
- **Tier A**: Sensible defaults for paper mode

**Findings:**
1. [A] Broker API keys in environment variables — not encrypted at rest
2. [A] TOTP secrets stored in plaintext — if env leaks, 2FA is compromised
3. [A] No audit log of credential access
4. [A] No rate limiting on auth endpoints
5. [A] No IP whitelisting for broker API access

---

## 13. Architecture Documentation vs. Reality

### Documented vs. Actual
| Claim | Documented In | Actual State | Verdict |
|-------|--------------|--------------|---------|
| 9 active agents | ARCHITECTURE.md | 9 agents confirmed healthy | ✅ Match |
| 14 strategies, 5 active | ARCHITECTURE.md | 3 active + 2 filters | ❌ Includes filters as "active" |
| stat_arb disabled | ARCHITECTURE.md | ACTIVE at runtime | ❌ Divergence |
| ML meta labeling integrated | docs/setup.md | Complete stub, no wiring | ❌ Not integrated |
| 4 broker connectors | ARCHITECTURE.md | 4 connector dirs (Angel, Kite, Groww, Jugaad) + Yahoo | ⚠️ Groww unwired |
| 30-day paper requirement | live_trading_gate.md | Burn-in timer exists | ✅ Defined |

**Findings:**
1. [A] Documentation claims stat_arb disabled — code says enabled — runtime confirms active
2. [A] Architecture doc overcounts active strategies by including filters
3. [A] ML integration is aspirational, not actual

---

## Cross-Cutting Themes

1. **Stale State**: TWAP orders survive restarts; kill-switch lost on Railway
2. **Unused Code**: Groww connector, HRP allocator, meta labeler, alternative data, strategy decay actions, latency tracer — all unwired
3. **Overfitting Risk**: Grid optimizer + walk-forward for 3/14 strats; no degradation-aware stop
4. **No Circuit Breaker Persistence**: Risk state lost on restart
5. **Paper Model Gaps**: No partial fills, no market impact, uniform latency
6. **Data Quality**: Backtest data provider accepts 0% coverage; synthetic ticks are sinusoidal
7. **Secrets in Plaintext**: All credentials in env vars, TOTP seeds unencrypted
8. **False Safety**: VaR returns `passed: True` with insufficient data; market impact model advisory-only

---

## Subsystem Score Summary

| Subsystem | Lines | Test Coverage | Health | Critical Issues |
|-----------|-------|--------------|--------|-----------------|
| Event Bus | 240 | Good | 🟢 | Backpressure drops audit trail |
| Strategy Engine | 435 | Good | 🟡 | stat_arb divergence, weight inflation |
| Execution | ~1400 | Good | 🟡 | Stale orders, partial fills missing |
| Risk Management | ~500 | Moderate | 🟡 | VaR false safe, kill-switch persistence |
| Connectors | ~1400 | Moderate | 🟡 | Groww dead, Angel slow, Yahoo unauthed |
| Backtest | 720 | Good | 🟡 | Paper fills, corporate actions missing |
| ML Layer | 75 | None | 🔴 | Complete stub |
| Portfolio | 117 | Minimal | 🟡 | HRP unwired |
| Analytics | 347 | Minimal | 🟡 | Decay detector unwired |
| Validation | 368 | Moderate | 🟡 | MC destroys autocorrelation |
| Monitoring | ~700 | Good | 🟢 | Latency tracer unwired |
| Security | ~80 | Minimal | 🟡 | Secrets in plaintext |

**Legend**: 🟢=Healthy 🟡=Needs Attention 🔴=Critical
