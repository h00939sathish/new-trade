# MASTER FINDINGS

## Legend

| Priority | Label | Meaning |
|---|---|---|
| P0 | Critical | Must fix before any deployment (paper or live). Active risk of financial loss or data exposure. |
| P1 | High | Must fix before live trading. Breaks core functionality or blocks safe operation. |
| P2 | Medium | Should fix. Adds safety, observability, or removes dead weight. Not blocking. |
| P3 | Low | Nice to have. Cleanup, documentation, or enhancements. |

---

## P0 — Critical (Fix Before Any Deployment)

| ID | Phase | Component | Summary | Evidence |
|---|---|---|---|---|
| F-021 | What Is Dangerous | HTTP Control | `/stop`, `/resume` endpoints unauthenticated by default. Anyone on network can: stop strategies, trigger flatten, wipe positions. | `src/main.py:144-155`: `auth_required` only checks blocklist; `src/config/settings.py:120-125`: `TRA_API_AUTH_TOKEN` has empty default. |
| F-020 | What Is Broken | KillSwitch | Race: concurrent trigger (P&L drop + drawdown) causes >1 flatten. Second flatten races position settle → partial fills → phantom inventory → silent drift. | `src/risk/kill_switch.py:89-95`: `if not self._triggered` then `self._triggered = True` is not atomic. |
| F-011 | What Is Broken | KillSwitch | `auto_reset=True` default means daily loss triggers kill switch at 9:15 AM, awaits no human, then resets at 10:00 AM or next day. Paper mode auto-recovers losses → no alarm. | `src/risk/kill_switch.py:35`: `auto_reset: bool = True`; `src/risk/kill_switch.py:120-125`: reset sets `_triggered = False`, clears `_triggered_at`. |
| F-018 | What Is Broken | StrategyGen (Gemini) | `api_key` passed as URL query parameter → logged in plaintext, visible in process lists, browser history. | `src/agents/strategy_gen.py:95`: `genai.configure(api_key=api_key)` pattern. |

### Fix Priority Order for P0
1. **F-021** — Add auth middleware to all HTTP endpoints; require `TRA_API_AUTH_TOKEN` in paper mode.
2. **F-020** — Use `asyncio.Lock` for `_triggered` check-and-set; reject flatten while flattening.
3. **F-011** — Change `auto_reset` default to `False`; add required env var override for True.
4. **F-018** — Switch to header-based auth for Gemini; redact from logs.

---

## P1 — High (Fix Before Live Trading)

| ID | Phase | Component | Summary | Evidence |
|---|---|---|---|---|
| F-012 | What Is Broken | Reconciliation | Broker fallback URL points to `http://localhost:5000` which is hardcoded and non-existent in paper. `connect` always fails silently. | `src/agents/reconciliation.py:60-65`: `broker_fallback_url = "http://localhost:5000"`. |
| F-013 | What Is Broken | Execution (burnin) | `_sync_state_with_broker` uses `run_in_executor` for blocking I/O but the sync is waited with `await` — blocks event loop during burnin. | `src/agents/execution.py:200-210`: `await loop.run_in_executor(None, self._sync_state_with_broker)`. |
| F-014 | What Is Broken | Execution | `_submit_approved_order` re-raises exceptions but caller `execute_order` catches `Exception` broadly. Partial failures go unlogged, unmonitored. | `src/agents/execution.py:350-360`: bare `raise`; `src/agents/execution.py:370`: `except Exception as e: self.logger.error(...)`. |
| F-015 | What Is Broken | SqliteEventStore | `serialize_event` emits `EventRecord` but `persist_events` expects `PersistableEvent` — 2 different schemas. Works by luck via duck-typing. | `src/event_store/sqlite.py:80-85` vs `src/event_store/sqlite.py:100-110`. |
| F-016 | What Is Broken | PostgresEventStore | Connection pool initialized in `__init__` without `async with`. Partial pool state on startup failure. | `src/event_store/postgres.py:45-50`: pool init not in async context manager. |
| F-017 | What Is Broken | ExecutionAgent (TWAP) | TWAP order internal state tracks `deleted=True` but parent order on `ExecutionAgent` is also deleted. Single delete = side effect. | `src/agents/execution.py:420-430`: `self._twap_orders[order_id] = None` before `await self._store.delete(order_id)`. |
| F-019 | What Is Broken | Execution | Paper mode: same order can be submitted N times via `/execute` endpoint — no idempotency key check. | `src/agents/execution.py:500-510`: no dedup on paper orders. |
| F-022 | What Is Dangerous | KillSwitch | Auto-reset silently re-enables trading without notifying operator. Daily loss pattern goes undetected. | `src/risk/kill_switch.py:120-130`: reset path logs "Kill switch auto-reset" at INFO level only. |
| F-023 | What Is Dangerous | KillSwitch | Flattening uses TWAP but no market impact model. For large NSE positions (>₹10L), TWAP slippage cancels the benefit of flattening. | `src/risk/kill_switch.py:140-150`: `flatten()` calls `execute_twap()` with no impact calc. |
| F-024 | What Is Dangerous | Execution (MIS→CO) | CO upgrade applies to all MIS orders regardless of broker capability or margin requirement. | `src/agents/execution.py:250-260`: blanket CO upgrade for MIS. |
| F-025 | What Is Dangerous | KillSwitch | `flatten()` sends `exit` for each open position but position size never validated against exchange lot size or limit. | `src/risk/kill_switch.py:140-150`: no `min(qty, exchange_limit)` check. |
| F-027 | What Is Dangerous | MarketIntel | No rate limiting on order placement. Saturation attack pattern possible via API replay. | `src/agents/execution.py:500-510`: no rate limiter. |
| F-034 | What Is Underengineered | KillSwitch | Zero integration tests for kill-switch lifecycle (trigger, flatten, persist, restore, auto-reset, manual override). | `tests/` grep for `kill_switch` returns no test files. |
| F-035 | What Is Underengineered | Reconciliation | No integration tests for drift alarm (broker vs local), fallback broker path, or reconciliation timeout. | `tests/` grep for `reconciliation` or `drift` returns no test files. |
| F-036 | What Is Underengineered | SL/TP | No integration tests for SL/TP execution path: trigger, order creation, fill simulation, trail update. | `tests/` grep for `stoploss`, `sl_tp`, `trailing` returns no test files. |
| F-037 | What Is Underengineered | System | No latency budget documented. No SLAs for: event bus delivery, order-to-fill, kill-switch trigger-to-flatten. | `docs/` has no latency/performance document. |
| F-038 | What Is Underengineered | Operations | No disaster recovery runbook. No documented procedure for: SQLite corruption, event store failure, broker API outage, system crash mid-order. | `docs/` has no DR runbook. |
| F-041 | What Is Missing | Risk | Per-symbol VaR limits not implemented. Portfolio-level VaR exists but can't restrict single-name blowup. | `src/risk/` no VaR module per symbol. |
| F-042 | What Is Missing | Risk | No overnight position tracking. End-of-day holdings not persisted for gap-risk monitoring. | `src/risk/position_registry.py`: no `overnight_positions` field. |
| F-044 | What Is Missing | Risk | No pre-trade margin check. Orders can exceed available margin with no rejection. | `src/risk/risk_mgmt.py`: checks position limits but not margin. |
| F-046 | What Is Missing | MarketIntel | No circuit breaker on broker connection. Connection drops cause silent stale price data until watchdog catches it. | `src/agents/market_intel.py`: no connection circuit breaker. |
| F-047 | What Is Missing | Execution | No order acknowledgement timeout. Orders may be "submitted" but never acknowledged → phantom fill risk. | `src/agents/execution.py`: no ack timer. |
| F-048 | What Is Missing | Operations | No trade journal export. All trade data locked in SQLite/event store. | `src/` no export module for trade journal. |

---

## P2 — Medium (Should Fix)

| ID | Phase | Component | Summary | Evidence |
|---|---|---|---|---|
| F-026 | What Is Dangerous | ReflectionEngine | Mutations auto-apply after grid search without human-in-the-loop review. LLM-generated parameters go live. | `src/agents/reflection_engine.py:200-210`. |
| F-028 | What Is Overengineered | KafkaEventStore | Kafka event store present in codebase with zero usage. Adds dependency surface + maintenance burden. | `src/event_store/kafka.py`: full module; `pyproject.toml`: kafka dep. |
| F-029 | What Is Overengineered | PortfolioOptimizer | Ledoit-Witt + scipy 4-regime optimization for 3 active strategies. Overkill. | `src/risk/portfolio_optimizer.py`: full module complexity. |
| F-030 | What Is Overengineered | Broker Connectors | 4 live broker stubs (Kite, Angel, Groww, IB) with zero live usage. Only paper simulator active. | `src/brokers/`: 4 connector modules. |
| F-031 | What Is Overengineered | Redis | Redis in docker-compose with zero usage anywhere in the codebase. | `docker-compose.yml`: Redis service. |
| F-032 | What Is Overengineered | PagerDuty | PagerDuty integration for paper mode. Fire drills over simulated losses. | `src/monitoring/pagerduty.py`: integration module. |
| F-033 | What Is Overengineered | Apache Flink | Flink listed as optional dependency with zero import or code path. | `pyproject.toml`: `streaming` extra includes Flink. |
| F-039 | What Is Underengineered | MarketIntel | No backpressure mechanism on market data ingestion. Burst can OOM or backlog event bus. | `src/agents/market_intel.py`: no backpressure. |
| F-040 | What Is Underengineered | Security | `.env` credential storage is gitignored (good) but no credential rotation policy, no vault integration, no audit log for credential access. | `.env.example` in repo. |
| F-043 | What Is Missing | Risk | Tax lot accounting is FIFO-only via Kelly sizing. No configurable lot selection method. | `src/risk/kelly_sizing.py`: FIFO hardcoded. |
| F-045 | What Is Missing | MarketIntel | Order book depth (bid/ask levels) not simulated from paper data. Only LTP-based fills. | `src/agents/market_intel.py`: no order book. |

---

## P3 — Low (Strengths & Nice-to-Haves)

| ID | Phase | Component | Summary | Evidence |
|---|---|---|---|---|
| F-001 | What Works | Architecture | Event-sourced architecture with 22 typed events is correct foundation. | `src/schemas/events.py`: complete event schema. |
| F-002 | What Works | PositionRegistry | Dual-locking (asyncio + threading) for thread-safe SSOT position tracking. | `src/risk/position_registry.py:45-50`: `_lock` + `_thread_lock`. |
| F-003 | What Works | KillSwitch | KillSwitch with persist+restore ensures state survives restart. | `src/risk/kill_switch.py:50-60`: `save()` + `load()`. |
| F-004 | What Works | T-Cost Model | 6-component NSE transaction cost model (STT, stamp duty, etc.) is thorough and accurate. | `src/risk/costs.py`: full NSE cost breakdown. |
| F-005 | What Works | PortfolioOptimizer | InstitutionalPortfolioOptimizer with 4 regimes is academically rigorous. | `src/risk/portfolio_optimizer.py`. |
| F-006 | What Works | Strategy Config | YAML-based strategy config with 12 strategies, weights, and filters is well-structured. | `src/config/strategy_config.py`. |
| F-007 | What Works | ADX Filter | ADX regime filter correctly gates strategies during ranging markets. | `src/agents/market_intel.py` ADX calc. |
| F-008 | What Works | VWAP Reversion | VWAP mean-reversion strategy is well-implemented with deviation bands. | `src/agents/strategy_gen.py`: VWAP regime. |
| F-009 | What Works | Event Store Abstraction | Clean abstract interface for event stores (SQLite/Postgres/Kafka) with factory pattern. | `src/event_store/__init__.py`: factory. |
| F-010 | What Works | Metrics Persistence | MetricsCollector with Prometheus format + SQLite persistence is production-ready. | `src/monitoring/metrics.py`. |

---

## Summary Statistics

| Priority | Count | % of Findings |
|---|---|---|
| P0 | 4 | 8.3% |
| P1 | 21 | 43.8% |
| P2 | 12 | 25.0% |
| P3 | 11 | 22.9% |
| **Total** | **48** | **100%** |

## Risk Heatmap

| Component | P0 | P1 | P2 | P3 | Risk Score |
|---|---|---|---|---|---|
| KillSwitch | 2 | 3 | 0 | 1 | **CRITICAL** |
| HTTP Control | 1 | 0 | 0 | 0 | **CRITICAL** |
| Gemini (API Key) | 1 | 0 | 0 | 0 | **CRITICAL** |
| ExecutionAgent | 0 | 4 | 0 | 0 | **HIGH** |
| Reconciliation | 0 | 1 | 0 | 0 | **HIGH** |
| Event Store | 0 | 2 | 1 | 1 | **MEDIUM** |
| Testing (missing) | 0 | 3 | 0 | 0 | **HIGH** |
| Operations | 0 | 2 | 0 | 0 | **HIGH** |
| Risk Engine | 0 | 3 | 1 | 0 | **MEDIUM** |
| Overengineering | 0 | 0 | 6 | 0 | **LOW** |
| Strengths | 0 | 0 | 0 | 11 | **NONE** |

> **Risk Score** is qualitative based on P0+P1 count impacting that component.
