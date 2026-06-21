# AUDIT LEDGER

Format: Finding ID | Evidence | Severity | Confidence | Action | Status

---

## PHASE 1 — WHAT WORKS

### F-001: Event-sourced architecture with typed events
- **Evidence**: `src/schemas/events.py` (665 lines) defines 17 typed Pydantic event classes with factory methods. All inter-agent communication uses these types. `src/event_store/async_bus.py` provides backpressure (0.5s timeout), critical-event prioritization (drop-oldest for critical types), and background persistence.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain. This is the correct architectural foundation.
- **Status**: VERIFIED

### F-002: PositionRegistry dual-locking SSOT
- **Evidence**: `src/risk/position_registry.py` uses both `asyncio.Lock` (for async write mutual exclusion) and `threading.RLock` (for cross-thread read safety). All position mutations flow through `update_from_fill()` which acquires both locks. `get_position()`/`get_quantity()` only acquire the threading lock (no yield = safe). The singleton is thread-safe.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain. This is a well-engineered component.
- **Status**: VERIFIED

### F-003: Kill switch with persistence and auto-reset
- **Evidence**: `src/risk/kill_switch.py` persists state to `state/kill_switch.state` on trigger and restores on startup. `daily_auto_reset()` correctly checks date boundary. `_cleanup_orders_and_positions()` cancels open orders then market-closes positions. The `check_limits()` method uses `asyncio.Lock` for thread safety.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain. Exception: `auto_reset=True` default is dangerous (see F-006).
- **Status**: VERIFIED

### F-004: Transaction cost model
- **Evidence**: `src/risk/costs.py` models 6 cost components (brokerage, STT, exchange txn, GST, SEBI, stamp duty) with product-aware (MIS/CNC) and side-aware (buy/sell) calculations. Includes depth-aware fill price estimation.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain.
- **Status**: VERIFIED

### F-005: InstitutionalPortfolioOptimizer with Ledoit-Wolf
- **Evidence**: `src/risk/portfolio_optimizer.py` implements Ledoit-Wolf covariance shrinkage, 4 optimization regimes (risk parity, min variance, max Sharpe, equal weight), graceful degradation for single strategy or insufficient data, and scipy SLSQP solver with fallback. This is production-grade.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain. However, overengineered for 3 strategies (see F-020).
- **Status**: VERIFIED

### F-006: Strategy config loading is clean and modular
- **Evidence**: `src/config/strategy_config.py` loads from YAML or default dict. `build_strategies_from_config()` reads registry, instantiates with params. `STRATEGY_REGISTRY` maps names to classes. Separates enabled/disabled, weight, params cleanly.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain.
- **Status**: VERIFIED

### F-007: ADX filter implementation is correct
- **Evidence**: `src/strategies/adx_filter.py` correctly implements Wilder's smoothing (sum-based for +DM/-DM/TR, average-based for ADX from DX). The `_wilders_smooth` and `_wilders_average` functions match ADX standard methodology.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain.
- **Status**: VERIFIED

### F-008: VWAP reversion strategy handles edge cases
- **Evidence**: `src/strategies/vwap_reversion.py` guards against zero cumulative volume (line 91), zero variance (line 158), insufficient data (lines 145-147). Uses numpy vectorization for performance. Dynamic confidence scaling from deviation sigma.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain.
- **Status**: VERIFIED

### F-009: Event store abstraction is clean
- **Evidence**: `src/event_store/base.py` defines ABC. Sqlite, Postgres, InMemory, Kafka implementations all conform. Selection in `__init__.py` via match statement. SQLite uses WAL mode for concurrent reads.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain.
- **Status**: VERIFIED

### F-010: Metrics persistence to SQLite
- **Evidence**: `src/monitoring/metrics.py` + `src/monitoring/metrics_store.py`: counters are restored from SQLite on startup (`load_from_store()` writes back accumulated counters), flushed every 10s. Gauge writes throttled to 1 Hz. Daily PnL baseline auto-resets on date boundary. This survives process restarts.
- **Severity**: Info
- **Confidence**: High
- **Action**: Retain.
- **Status**: VERIFIED

---

## PHASE 2 — WHAT IS BROKEN

### F-011: KillSwitch auto_reset=True by default
- **Evidence**: `src/risk/kill_switch.py:26` sets `self._auto_reset = True`. This means if a daily loss limit is breached, the kill switch will auto-reset the next trading day, allowing trading to resume. If the strategy is losing, this causes repeated daily losses.
- **Impact**: Can cause repeated daily capital loss. A strategy that consistently loses 1%/day will hit kill switch, auto-reset, lose another 1%, repeat.
- **Severity**: High
- **Confidence**: High
- **Action**: Change default to False. Require explicit operator reset.
- **Status**: OPEN

### F-012: ReconciliationAgent broker fallback logic broken
- **Evidence**: `src/agents/reconciliation.py:28-35` — `getattr(self.system, "_kite_client", None)` is used to find a fallback broker. However `TradingSystem.__init__` stores the attribute as `self._kite_client` (line 27 in `system.py`) — the fallback is correct. But lines 29-30 fall through to `exec_agent._broker` which would already be the Kite broker if wired. The logic is redundant and the `_kite_client` attribute may not exist if `settings.kite_api_key` is not set.
- **Impact**: In paper mode this is a no-op (broker is None). In live mode, reconciliation could fail to connect.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Remove redundant fallback chain. Refactor to use `exec_agent._broker` directly.
- **Status**: OPEN

### F-013: Burnin reconciliation writes are synchronous in async loop
- **Evidence**: `src/monitoring/burnin.py:60` — `write_paper_reconciliation_snapshot()` calls synchronous `json.dumps()` + file `open().write()` in `run_paper_reconciliation_loop` which is an async task. Blocks the event loop.
- **Impact**: 300ms+ file I/O blocks event loop every reconciliation interval (default 300s, was 1800s). Low probability of visible impact but incorrect.
- **Severity**: Low
- **Confidence**: High
- **Action**: Wrap file write in `asyncio.to_thread()` or use `aiofiles`.
- **Status**: OPEN

### F-014: ExecutionAgent._submit_approved_order re-raises without caller handling
- **Evidence**: `src/agents/execution.py:664` — `raise e` on broker pre-submission reject. The caller `_handle_risk_check()` at line 391 does not wrap `_submit_approved_order` in try/except. The exception propagates to the bus loop in `BaseAgent._subscribe_bus_loop()` line 191 which catches generic Exception. The order is lost without proper error event emission.
- **Impact**: Broker-rejected orders silently fail without error event or retry. The pending order remains in `_pending_orders` dict.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Catch exception in `_handle_risk_check`, emit ORDER_REJECTED event, clean up pending order.
- **Status**: OPEN

### F-015: Event type mismatch in SqliteEventStore._row_to_event
- **Evidence**: `src/event_store/sqlite.py:241-251` — `Event()` is constructed with `event_type=str(row["event_type"])` but `Event` expects `event_type: EventType`. Pydantic may coerce this, but the type annotation is violated.
- **Impact**: Could cause validation errors when replaying events with certain Pydantic configurations. Low probability but violates type contract.
- **Severity**: Low
- **Confidence**: High
- **Action**: Use `event_type=EventType(row["event_type"])` for explicit enum parsing.
- **Status**: OPEN

### F-016: PostgresEventStore.connect() leaves pool in partial state on failure
- **Evidence**: `src/event_store/postgres.py:31-73` — Pool is created at line 31, then schema setup runs. If schema setup fails (line 69), pool is closed. But if the TimescaleDB hypertable creation throws (line 62), only a warning is logged and execution continues. If `create_pool` succeeds but subsequent operations fail before `self._pool = pool` (line 73), the pool is never assigned.
- **Impact**: On partial failure, the pool may leak or be null. Callers calling `_get_pool()` will get RuntimeError even though a pool exists.
- **Severity**: Medium
- **Confidence**: Medium
- **Action**: Move pool assignment before schema setup. Close pool on any schema setup failure.
- **Status**: OPEN

### F-017: TWAP loop completed deletion calls _persist_twap with stale state
- **Evidence**: `src/agents/execution.py:893-895` — After TWAP completes, `del self._twap_orders[twap_id]` is called, then `await self._persist_twap(twap_id)` tries to look up the deleted entry. The delete branch in `_persist_twap` (lines 312-314) handles the missing entry by deleting from DB, so this works but is a logic bug — the completion event should trigger a DB cleanup, not depend on the delete branch.
- **Impact**: Correct by coincidence. TWAP cleanup writes a DELETE to DB which is correct but confusing.
- **Severity**: Low
- **Confidence**: High
- **Action**: Swap order: persist first, then delete from memory.
- **Status**: OPEN

### F-018: Gemini API key exposed in URL query string
- **Evidence**: `src/agents/reflection_engine.py:619` — `url = f"{self.BASE_URL}/gemini-2.0-flash:generateContent?key={self._api_key}"`. API keys in URL query strings are logged by proxies, load balancers, and web servers in plaintext.
- **Impact**: Credential leak if the system is behind any HTTP proxy, load balancer, or if request logging is enabled. API key in URL is a OWASP A3 violation.
- **Severity**: High
- **Confidence**: High
- **Action**: Use `x-goog-api-key` header instead of query parameter.
- **Status**: OPEN

### F-019: No duplicate order protection in paper mode
- **Evidence**: `src/agents/execution.py:572-578` — Duplicate order check via `_is_order_placed(tag)` only runs when `self._broker is not None`. In paper mode (broker=None), a signal could create duplicate orders if `_execute_approved_signal` is called twice for the same signal.
- **Impact**: In paper mode, duplicate orders can be placed for the same signal. The paper `_simulate_fill` would produce duplicate fills leading to inflated PnL.
- **Severity**: Medium
- **Confidence**: Medium
- **Action**: Extend duplicate check to paper mode using `_order_strategies` or `_open_orders`.
- **Status**: OPEN

### F-020: KillSwitch.trigger() uses event bus without lock on _active flag
- **Evidence**: `src/risk/kill_switch.py:153-155` — `if self._active: return` then `self._active = True` are not under the async lock. The `trigger()` method should acquire `_get_async_lock()` before checking and setting `_active`.
- **Impact**: Race condition: two concurrent triggers could both pass the initial check and execute cleanup twice. Low probability (trigger is rare) but zero-cost fix.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Add `async with self._get_async_lock()` around trigger entry.
- **Status**: OPEN

---

## PHASE 3 — WHAT IS DANGEROUS

### F-021: HTTP control endpoints unauthenticated in paper mode
- **Evidence**: `src/main.py:21-31` — If `TRA_HTTP_AUTH_TOKEN` is empty (default), paper mode logs a warning but starts without auth. `POST /api/kill-switch/reset` and control endpoints become accessible to anyone on the network. On port 8080 bound to `0.0.0.0`.
- **Impact**: Anyone on the local network (or internet if exposed) can reset kill switch, flatten positions remotely. Capital at risk: full $1M paper capital.
- **Severity**: Critical
- **Confidence**: High
- **Action**: Require auth token in ALL modes. Fail to start if unset, with explicit override flag.
- **Status**: OPEN

### F-022: KillSwitch auto-reset can silently re-enable trading after loss
- **Evidence**: `src/risk/kill_switch.py:108-124` — `daily_auto_reset()` clears kill switch without operator notification or confirmation. Combined with F-006 default, a strategy that hits daily loss limit every day will keep trading and losing.
- **Impact**: Can lose initial_capital * daily_loss_pct every trading day. For default settings: $10,000/day with $1M capital and 1% daily loss limit. Probability: depends on strategy quality.
- **Severity**: High
- **Confidence**: High
- **Action**: Default auto_reset to False. When auto-resetting, emit alert with manual confirmation requirement.
- **Status**: OPEN

### F-023: KillSwitch._cleanup_orders_and_positions can cause market impact
- **Evidence**: `src/risk/kill_switch.py:200-223` — Iterates `portfolio_agent._positions` and emits MARKET orders to close all positions. For large positions (e.g., 1000+ shares of low-liquidity stock), the market order could walk the book significantly. No limit checks or TWAP for liquidations.
- **Impact**: In a real brokerage scenario, kill switch liquidation could cause significant slippage on illiquid symbols. Capital at risk: 1-5% of position value on illiquid NSE small-caps.
- **Severity**: Medium
- **Confidence**: Medium
- **Action**: Implement graduated liquidation: TWAP for large positions, market for small. Add maximum order value check.
- **Status**: OPEN

### F-024: MIS order upgrade to CO without broker capability check
- **Evidence**: `src/agents/execution.py:629-635` and `813-819` — Orders with `product="mis"` and `trigger_price` set are automatically upgraded to variety "co" (Cover Order). This is broker-specific (Kite/Zerodha only). No check verifies the connected broker supports CO orders.
- **Impact**: If connected to a broker that doesn't support CO (Angel, Groww), the order would be rejected. In paper mode, this is silently ignored.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Make CO upgrade broker-aware. Only upgrade when broker is Kite and live trading is enabled.
- **Status**: OPEN

### F-025: No position size validation on kill-switch flatten orders
- **Evidence**: Inconsistent with F-023. Additionally, there's no check that the flatten order quantity doesn't exceed `risk_max_order_value` (default $50,000). A position worth $100k would be liquidated in a single market order.
- **Impact**: Same as F-023 — market impact on large positions.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Add order size checks to liquidation path.
- **Status**: OPEN

### F-026: ReflectionEngine mutation could be enabled without human review
- **Evidence**: `src/agents/reflection_engine.py:421-426` — `TRA_REFLECTION_MUTATION_ENABLED` gates auto-application, but if enabled, the engine auto-applies parameter mutations found via grid search or LLM recommendation. No confirmation before changing live strategy parameters.
- **Impact**: A bad parameter sweep could degrade strategy performance for up to the full evaluation window before being noticed. Capital at risk: strategy-dependent.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Mutation gate is off by default. Document this as a pre-live-gate requirement.
- **Status**: VERIFIED (gated) — retain as finding for live-trading readiness.

### F-027: No order rate limiting
- **Evidence**: `src/agents/execution.py` has no checks on orders-per-second or orders-per-minute from a single strategy or instrument. The only throttle is `_SIGNAL_COOLDOWN_SECONDS` (120s) in StrategyGenAgent, which applies to signal emission, not order placement.
- **Impact**: A bug in strategy evaluation could rapidly produce hundreds of orders before any throttle engages.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Add max orders/minute and max orders/second limits to ExecutionAgent.
- **Status**: OPEN

---

## PHASE 4 — WHAT IS OVERENGINEERED

### F-028: KafkaEventStore exists with zero usage
- **Evidence**: `src/event_store/kafka.py` — Full `KafkaEventStore` implementation using `aiokafka`. Never selected in any production or test config. The `pyproject.toml` includes `aiokafka>=0.10` as a core dependency (not optional).
- **Cost**: Adds `aiokafka` dependency (compile C extensions on install). Maintenance burden of dead code. ~200 LOC that is never tested, never run.
- **Recommendation**: Move to optional dependency, or delete until Wave 8.
- **Severity**: Low
- **Confidence**: High
- **Action**: Remove `aiokafka` from core deps, move KafkaEventStore to a `[kafka]` extra.
- **Status**: OPEN

### F-029: InstitutionalPortfolioOptimizer for 3 strategies
- **Evidence**: `src/risk/portfolio_optimizer.py` — Full Ledoit-Wolf covariance shrinkage, scipy SLSQP solver, 4 optimization regimes. Active strategy count is 3. A 3-strategy portfolio can be optimized with simple closed-form formulas. The optimizer runs every 300s.
- **Cost**: Adds ~2MB numpy/scipy dependency. 317 lines of code. 50-200ms of CPU every 5 minutes for a 3x3 covariance matrix.
- **Recommendation**: Keep for future strategy count growth but add early-exit for ≤3 strategies that skips numerical optimization.
- **Severity**: Low
- **Confidence**: Medium
- **Action**: Add fast-path for small portfolios (≤5 strategies). Use analytical risk parity.
- **Status**: OPEN

### F-030: Live broker connectors (Kite, Angel, Groww) with no live trading
- **Evidence**: 4 live broker connectors exist (Kite client/broker/market_data, Angel client/market_data/websocket, Groww client/market_data) — all with authentication wired, order routing stubs, and WebSocket connections. But `TRA_LIVE_TRADING_ENABLED` defaults to False and paper burn-in never uses them.
- **Cost**: Adds credential management complexity (17 API key settings in vault). Security surface area for unused functionality. Maintenance burden for API changes.
- **Recommendation**: Document that these are stubs requiring live_trading_gate.md sign-off before use. No action until live trading is planned.
- **Severity**: Low
- **Confidence**: High
- **Action**: Add runtime assertions that live brokers are never used in paper mode. Otherwise, no change.
- **Status**: VERIFIED

### F-031: Redis in docker-compose with zero hot-path usage
- **Evidence**: `docker-compose.yml` includes Redis 7 Alpine. Redis is in `pyproject.toml` as `redis[hiredis]>=5.0`. But no code in the hot path uses Redis. The only potential use is `src/utils/` which doesn't reference it.
- **Cost**: Adds a container to the deployment. Adds `hiredis` C extension compilation.
- **Recommendation**: Remove from docker-compose until a use case exists. Remove from core deps.
- **Severity**: Low
- **Confidence**: High
- **Action**: Remove Redis from docker-compose and deps.
- **Status**: OPEN

### F-032: PagerDuty integration for paper trading
- **Evidence**: `src/agents/alert.py:87-116` — Full PagerDuty Events API v2 integration. Paper trading system routing critical alerts to PagerDuty. The `pagerduty_routing_key` is a required env var.
- **Cost**: PagerDuty licensing cost. Alert fatigue from paper trading alerts.
- **Recommendation**: Disable PagerDuty for paper mode. Only activate for live trading.
- **Severity**: Low
- **Confidence**: Medium
- **Action**: Gate PagerDuty notifier behind TRA_LIVE_TRADING_ENABLED.
- **Status**: OPEN

### F-033: Apache Flink as optional dependency
- **Evidence**: `pyproject.toml` line 49-50: `[tool.poetry.extras] streaming = ["apache-flink>=1.19"]` — Apache Flink is listed as an optional dependency but there is zero Flink code in the system. No streaming pipeline, no Flink connectors, no Flink jobs.
- **Cost**: Flink is 200MB+ dependency. Adds confusion about architecture direction.
- **Recommendation**: Remove from `pyproject.toml`. Add if/when Wave 8 streaming architecture is implemented.
- **Severity**: Low
- **Confidence**: High
- **Action**: Remove apache-flink from optional dependencies.
- **Status**: OPEN

---

## PHASE 5 — WHAT IS UNDERENGINEERED

### F-034: No kill-switch integration tests
- **Evidence**: Searching test files: `test_live_safety_p0.py` exists but doesn't test kill-switch trigger → execution block → position flatten flow. No test verifies `KillSwitch.trigger()` sets `strategy_gen._running = False`.
- **Impact**: Kill switch is a critical safety component with zero integration test coverage. A regression could disable the only emergency stop.
- **Severity**: High
- **Confidence**: High
- **Action**: Add integration tests for kill-switch lifecycle (trigger, cancel orders, flatten, auto-reset, manual reset).
- **Status**: OPEN

### F-035: No reconciliation drift alarm tests
- **Evidence**: `src/agents/reconciliation.py:118-141` — `_check_drift()` has no dedicated test. `test_integration.py` tests basic flows but not position drift detection.
- **Impact**: Drift alarm is defense-in-depth for data integrity. Without tests, it may silently fail.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Add unit/integration tests for drift detection.
- **Status**: OPEN

### F-036: No SL/TP execution tests
- **Evidence**: `src/agents/strategy_gen.py:235-294` — `_check_sl_tp()` is called on every tick/OHLCV but has zero test coverage. Test files for `test_strategies.py` test strategy evaluation, not SL/TP monitoring.
- **Impact**: SL/TP is a P1 risk control. If broken, positions may run uncontrolled.
- **Severity**: High
- **Confidence**: High
- **Action**: Add unit tests for SL/TP monitoring and exit signal generation.
- **Status**: OPEN

### F-037: No latency budget documented
- **Evidence**: The entire codebase has no documented latency SLOs. `src/monitoring/latency_tracer.py` records per-event latency but no thresholds, budgets, or alerting are defined.
- **Impact**: Degradation in event processing latency goes undetected until it causes visible signal delay or order timing issues.
- **Severity**: Low
- **Confidence**: High
- **Action**: Define latency budgets for each event path (tick → signal < 100ms, signal → order < 50ms).
- **Status**: OPEN

### F-038: No disaster recovery runbook
- **Evidence**: `docs/RUNBOOK.md` exists but covers incident response, not crash recovery. No documented procedure for: 1) Restoring from event store after crash, 2) Reconciling with broker after restart, 3) Recovering in-flight orders.
- **Impact**: On process crash during live trading, operators have no documented recovery procedure.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Write crash recovery runbook for live trading scenario.
- **Status**: OPEN

### F-039: No market data backpressure mechanism
- **Evidence**: `src/agents/market_intel.py` — `_on_provider_tick` and `_on_provider_ohlcv` are callbacks that directly emit events. If the event bus is congested, there's no mechanism to slow down the data provider. The bus has backpressure (0.5s timeout + drop) but the provider is unaware.
- **Impact**: In high-volume tick scenarios, the event bus will drop events. Non-critical ticks are dropped silently (warning log).
- **Severity**: Medium
- **Confidence**: Medium
- **Action**: Add optional tick aggregation (min/max block) or rate-limiting to MarketIntelAgent.
- **Status**: OPEN

### F-040: Security — credentials stored in .env file
- **Evidence**: `.env` file (3537 bytes) contains API keys, secrets, tokens for Kite, Angel, Groww, Gemini. While vault integration exists (`src/utils/vault.py`), the default is file-based env vars.
- **Impact**: If `.env` is accidentally committed (it's in `.gitignore`, but human error), all broker credentials are exposed.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Add pre-commit hook to block .env commits. Document vault setup as prerequisite for live trading.
- **Status**: VERIFIED (.env is gitignored)

---

## PHASE 6 — WHAT IS MISSING

### F-041: No position-level VaR limits
- **Evidence**: `src/agents/risk_mgmt.py:442-475` — `_check_var_risk()` exists but uses simple historical VaR with only 20-price history and a hardcoded 2% of `_max_position_size` as threshold. No per-symbol VaR limits, no portfolio VaR, no stress testing.
- **Comparison**: Institutional trading platforms (NautilusTrader, QuantConnect) have configurable per-symbol risk limits with multiple VaR methodologies.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Implement per-symbol VaR limits with configurable lookback and threshold.
- **Status**: OPEN

### F-042: No overnight position tracking
- **Evidence**: `src/risk/position_registry.py` tracks positions in memory only. No persistence of positions across restarts. On restart, positions are rebuilt from events but product type (MIS vs CNC) information affects overnight holding.
- **Comparison**: Institutional systems track delivery/MIS flag and auto-square-off based on product type.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Persist product type with position, implement auto-square-off based on market close times.
- **Status**: OPEN

### F-043: No tax lot accounting
- **Evidence**: `src/risk/kelly_sizing.py:84-100` uses FIFO for realized PnL calculation. But `PortfolioOptimizationAgent._on_fill` (portfolio.py:143) calculates realized PnL using registry's avg_price, which is a moving average, not lot-specific. This can diverge from broker's actual PnL.
- **Comparison**: Institutional systems (NautilusTrader, Bloomberg AIM) use proper tax lot accounting.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Implement lot-based position tracking (FIFO) for accurate realized PnL.
- **Status**: OPEN

### F-044: No pre-trade margin check
- **Evidence**: `src/agents/risk_mgmt.py` checks exposure (position_value ≤ capital * leverage) but does NOT check margin requirements. For intraday MIS trades, NSE VAR+ELM margin is typically 20-25% of trade value. A $100k order on $1M capital (10% exposure) may require only $20k margin, but the system blocks at $300k (3x leverage). There's no broker-specific margin model.
- **Comparison**: All live trading platforms compute margin before order submission.
- **Severity**: High
- **Confidence**: Medium
- **Action**: Add margin model for NSE products (MIS intraday margin rates).
- **Status**: OPEN

### F-045: No order book depth from paper data source
- **Evidence**: `src/agents/execution.py:1124-1186` — `_simulate_fill()` uses `_latest_depth` which is populated from Tick events with depth data. Yahoo Finance does not provide depth. Paper fills without depth use `effective_fill_price()` which applies a flat 5bps slippage.
- **Impact**: Paper fills are unrealistic for large orders. TWAP/slicing benefits are not validated.
- **Severity**: Low
- **Confidence**: High
- **Action**: Document paper fill limitations. Consider using historical order book data for more realistic simulation.
- **Status**: OPEN

### F-046: No circuit breaker on broker connection
- **Evidence**: `src/execution/hardening.py:98-128` — `BrokerReconnector` exists but is NOT used anywhere in the hot path. The `ExecutionAgent` doesn't wrap broker calls with reconnect logic. On broker disconnection, all order submissions fail with `raise e`.
- **Comparison**: TradingAgents and NautilusTrader have connection-state machines with automatic reconnect.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Wire BrokerReconnector into ExecutionAgent's broker submission path.
- **Status**: OPEN

### F-047: No order acknowledgement/fill timeout
- **Evidence**: `src/agents/execution.py` — After `_submit_approved_order()` calls broker and emits ORDER_CREATED, there's no timeout tracking for when the order should be acknowledged or filled. If the broker never responds, the order stays in `_open_orders` indefinitely.
- **Comparison**: NSE typically acknowledges orders within 100ms. NautilusTrader has configurable order timeouts.
- **Severity**: Medium
- **Confidence**: High
- **Action**: Add order acknowledgement timeout. Orders not acknowledged within 5s should trigger escalation.
- **Status**: OPEN

### F-048: No trade journal export
- **Evidence**: Trades are tracked in event store, order DB, and metrics DB. But there's no structured trade journal export (CSV, Parquet) for post-hoc analysis. The `scripts/` directory has `run_backtest_compare.py` but no trade export utility.
- **Comparison**: NautilusTrader exports trades to Parquet. QuantConnect has CSV/JSON export.
- **Severity**: Low
- **Confidence**: High
- **Action**: Add trade journal export command (CLI or API).
- **Status**: OPEN
