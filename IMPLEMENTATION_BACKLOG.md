# IMPLEMENTATION BACKLOG

## How to Use

| Priority | Label | Timeline |
|---|---|---|
| P0 | Critical | Before any deployment |
| P1 | High | Before live trading |
| P2 | Medium | Next sprint after live |
| P3 | Low | Backlog |

Each ticket includes: **Summary**, **Component**, **Acceptance Criteria (AC)**, **Rollback Strategy**, **Affected Files**.

---

## P0 — Critical (Fix Before Any Deployment)

### T-001: Add Authentication to HTTP Control Endpoints

| Field | Value |
|---|---|
| **F-Ref** | F-021 |
| **Component** | HTTP Control / `main.py` |
| **Severity** | CRITICAL — unauthenticated network access to kill switch |

**AC:**
- All HTTP endpoints (`/stop`, `/resume`, `/flatten`, `/status`, `/config`) require bearer token when `TRA_API_AUTH_TOKEN` is set.
- Missing/invalid token returns 401 with no stack trace.
- `TRA_API_AUTH_TOKEN` is required (non-empty) when `TRA_LIVE_TRADING_ENABLED=False` in paper mode; the code must fail at startup if it's empty.
- Auth bypass via `X-Forwarded-For` or `X-Auth-Bypass` headers is not possible.
- Token comparison is constant-time (no timing side channel).

**Rollback:**
- Revert `src/main.py` auth middleware block; restore `auth_bypass` flag.

**Affected Files:**
- `src/main.py` (add middleware)
- `src/config/settings.py` (validate TRA_API_AUTH_TOKEN not empty)
- `src/middleware/auth.py` (new file — bearer token middleware)
- `tests/test_auth.py` (new — auth test suite)

---

### T-002: Fix KillSwitch Trigger Race Condition

| Field | Value |
|---|---|
| **F-Ref** | F-020 |
| **Component** | KillSwitch |
| **Severity** | CRITICAL — double flatten → phantom inventory → silent drift |

**AC:**
- `_triggered` flag is set atomically within `asyncio.Lock`.
- Concurrent P&L and drawdown triggers result in exactly one flatten execution.
- While flattening, a `Lock` or state flag prevents a second flatten from starting.
- After flatten completes (success or failure), the lock is released.
- Unit test: fire 10 concurrent triggers → verify `flatten()` called exactly once.
- Unit test: fire trigger while flatten in progress → verify second call is a no-op.

**Rollback:**
- Revert the lock + atomic-check change; restore simple boolean flag.

**Affected Files:**
- `src/risk/kill_switch.py` (add `asyncio.Lock`, atomic check-and-set)
- `tests/test_kill_switch.py` (new — concurrent trigger tests)

---

### T-003: Change KillSwitch `auto_reset` Default to False

| Field | Value |
|---|---|
| **F-Ref** | F-011 |
| **Component** | KillSwitch |
| **Severity** | CRITICAL — daily loss silently auto-recovers |

**AC:**
- `auto_reset` defaults to `False`.
- Auto-reset only possible with explicit `TRA_KILL_SWITCH_AUTO_RESET=True` env var.
- When auto-reset is `False`, reset requires explicit HTTP call or CLI command.
- Documentation clearly states the risk of enabling auto-reset.
- Logging at WARN level when auto-reset is enabled.
- Migration path: existing `kill_switch_state.json` files from `True` default are handled gracefully (no crash on load).

**Rollback:**
- Set default back to `True`; document as deprecated.

**Affected Files:**
- `src/risk/kill_switch.py` (change default)
- `src/config/settings.py` (add `TRA_KILL_SWITCH_AUTO_RESET` env var)
- `docs/operations.md` (update section on auto-reset)

---

### T-004: Fix Gemini API Key Exposure

| Field | Value |
|---|---|
| **F-Ref** | F-018 |
| **Component** | StrategyGen / ReflectionEngine |
| **Severity** | CRITICAL — API key leaked in URL, logs, process list |

**AC:**
- API key passed via `X-Goog-Api-Key` header or `genai.configure(api_key=...)` without query parameter fallback.
- API key is never logged, printed, or included in exception messages.
- If logging of outgoing HTTP requests exists, the `api_key` parameter is redacted.
- Existing log files and `.env` comments warn about key handling.

**Rollback:**
- Revert to query-param auth with added documentation.

**Affected Files:**
- `src/agents/strategy_gen.py` (switch to header auth)
- `src/agents/reflection_engine.py` (verify same pattern)
- `tests/test_strategy_gen.py` (verify key not in logs)

---

## P1 — High (Fix Before Live Trading)

### T-005: Fix ReconciliationAgent Broker Fallback URL

| Field | Value |
|---|---|
| **F-Ref** | F-012 |
| **Component** | Reconciliation |
| **Severity** | HIGH — drift detection broken in paper mode |

**AC:**
- Broker fallback URL is configurable via setting, not hardcoded.
- Paper mode uses a dedicated paper broker simulator URL, not `localhost:5000`.
- If broker connect fails, reconciliation degrades gracefully (logs warning, does not block event loop).
- Reconcilation timeout is configurable.
- Unit test: mock broker connect failure → verify reconciliation logs warning and continues.

**Rollback:**
- Revert URL changes; restore `localhost:5000` as placeholder.

**Affected Files:**
- `src/agents/reconciliation.py` (configurable URL, graceful degradation)
- `src/config/settings.py` (add `TRA_RECONCILIATION_BROKER_URL`)

---

### T-006: Fix Blocking Sync in Burnin

| Field | Value |
|---|---|
| **F-Ref** | F-013 |
| **Component** | Execution (burnin) |
| **Severity** | HIGH — blocks event loop during startup |

**AC:**
- Burnin sync uses a dedicated thread (or `asyncio.to_thread`) without `await` on the sync operation itself.
- Event loop is not blocked during burnin; other agents can process events.
- Sync has a timeout; if it exceeds the timeout, burnin completes with partial state and a warning log.
- Unit test: inject slow sync → verify event loop remains responsive.

**Rollback:**
- Revert to synchronous sync with timeout documentation.

**Affected Files:**
- `src/agents/execution.py` (refactor burnin sync to non-blocking)

---

### T-007: Add Order Acknowledgement Timeout

| Field | Value |
|---|---|
| **F-Ref** | F-047 |
| **Component** | Execution |
| **Severity** | HIGH — phantom fill risk if order not acknowledged |

**AC:**
- Every submitted order has an acknowledgement timer (configurable, default 30s).
- If no ack received within timeout, order transitions to `ORDER_UNACKED` event.
- Unacked order triggers a WARN log, an alert metric increment, and an optional retry.
- After N consecutive timeouts (configurable), execution for that symbol pauses.
- Unit test: submit order, don't ack → verify `ORDER_UNACKED` event emitted.

**Rollback:**
- Remove timer logic; default to no timeout.

**Affected Files:**
- `src/agents/execution.py` (ack timer, retry logic)
- `src/schemas/events.py` (add `ORDER_UNACKED` event type)
- `src/monitoring/metrics.py` (add ack timeout counter)

---

### T-008: Add Duplicate Order Protection in Paper Mode

| Field | Value |
|---|---|
| **F-Ref** | F-019 |
| **Component** | Execution |
| **Severity** | HIGH — duplicate orders via `/execute` |

**AC:**
- Every order has a client-supplied `order_id` (idempotency key).
- Paper executor checks `order_id` against recent order cache before submission.
- Duplicate `order_id` returns existing order status, does not create new order.
- Cache TTL is configurable (default 5 minutes after terminal state).
- Idempotency check is persistent (survives restart via event store replay).
- Unit test: submit same order_id twice → verify only one order created.
- Unit test: submit same order_id after restart → verify idempotency from event store.

**Rollback:**
- Disable idempotency check; restore submit-as-new behavior.

**Affected Files:**
- `src/agents/execution.py` (idempotency cache, check wrapper)
- `src/schemas/events.py` (ensure `order_id` is required field)
- `src/risk/position_registry.py` (verify no double-count from duplicate orders)

---

### T-009: Add Order Rate Limiting

| Field | Value |
|---|---|
| **F-Ref** | F-027 |
| **Component** | Execution |
| **Severity** | HIGH — no rate limit on order placement |

**AC:**
- Rate limiter configured per-symbol and globally (configurable, e.g., 10 orders/sec per symbol, 50/sec globally).
- Token-bucket algorithm.
- Exceeded rate → order queued with configurable max queue depth.
- Queue overflow → order rejected with `ORDER_REJECTED` event.
- Rate limit config exposed via settings.
- Unit test: fire 100 instant orders → verify only N pass.
- Unit test: verify rate limit resets correctly after window.

**Rollback:**
- Remove rate limiter middleware; restore pass-through.

**Affected Files:**
- `src/agents/execution.py` (add rate limiter)
- `src/execution/throttle.py` (new — token-bucket implementation)
- `src/config/settings.py` (rate limit parameters)

---

### T-010: Add Pre-Trade Margin Check

| Field | Value |
|---|---|
| **F-Ref** | F-044 |
| **Component** | Risk |
| **Severity** | HIGH — orders can exceed available margin |

**AC:**
- Margin calculator computes required margin per order (NSE: MIS intraday = ~20%, CNC delivery = 100%, CO = VAR + ELM).
- Pre-trade check: `required_margin >= available_margin` → order rejected with `ORDER_REJECTED` event, reason = `INSUFFICIENT_MARGIN`.
- Available margin computed from cash balance + open position P&L.
- Margin check runs before position limit checks.
- Configurable `min_margin_buffer` (spread above required margin).
- Unit test: submit order exceeding margin → verify rejection.
- Unit test: submit order within margin → verify approval.

**Rollback:**
- Disable margin check; skip validation.

**Affected Files:**
- `src/risk/margin.py` (new — margin calculator)
- `src/risk/risk_mgmt.py` (add margin check to pre-trade checks)
- `src/schemas/events.py` (add `INSUFFICIENT_MARGIN` rejection reason)
- `src/config/settings.py` (margin parameters)

---

### T-011: Add Per-Symbol VaR Limits

| Field | Value |
|---|---|
| **F-Ref** | F-041 |
| **Component** | Risk |
| **Severity** | HIGH — can't restrict single-name blowup |

**AC:**
- VaR computed per symbol: `VaR(95%, 1d) = -percentile(daily_returns, 5)`.
- Per-symbol VaR limit in config (e.g., `max_var_per_symbol: 0.05` meaning 5% of portfolio).
- If symbol VaR exceeds limit, new orders for that symbol are rejected.
- Existing positions exceeding limit trigger a WARN log but are not auto-liquidated.
- VaR calculation uses at least 20 trading days of history.
- Unit test: symbol with VaR 6% with limit 5% → orders rejected.

**Rollback:**
- Remove VaR check; restore per-symbol position limits only.

**Affected Files:**
- `src/risk/var.py` (new — VaR calculator)
- `src/risk/risk_mgmt.py` (add VaR check)
- `src/config/strategy_config.py` (VaR limit parameters)
- `tests/test_var.py` (new)

---

### T-012: Add Overnight Position Tracking

| Field | Value |
|---|---|
| **F-Ref** | F-042 |
| **Component** | Risk |
| **Severity** | HIGH — no gap-risk monitoring |

**AC:**
- EOD snapshot of all open positions persisted to event store with timestamp.
- Gap risk computed as `abs(holdings) * max(historical_gap_1d)` per symbol.
- If gap risk > warning threshold, WARN log emitted at market close.
- Overnight positions displayed in `/status` HTTP endpoint.
- Overnight tracking survives restart (persisted to event store).
- Unit test: open position at 3:30 PM → verify EOD snapshot created.
- Unit test: restart with overnight positions → verify restored.

**Rollback:**
- Remove EOD snapshot logic; restore open-only position tracking.

**Affected Files:**
- `src/risk/position_registry.py` (add overnight snapshot)
- `src/schemas/events.py` (add `EOD_POSITION_SNAPSHOT` event)
- `src/main.py` (add EOD timer)
- `tests/test_overnight.py` (new)

---

### T-013: Add Circuit Breaker on Broker Connection

| Field | Value |
|---|---|
| **F-Ref** | F-046 |
| **Component** | MarketIntel |
| **Severity** | HIGH — stale data during connection drops |

**AC:**
- Circuit breaker monitors broker connection health (heartbeat or data freshness).
- After N consecutive failures (configurable, default 3), circuit opens.
- Open circuit: no new data from that broker; latest known price used with staleness flag.
- After cooldown (configurable, default 60s), circuit transitions to half-open.
- Half-open: one probe request; if successful → circuit closes; if fail → back to open.
- Circuit state changes logged at WARN level and exposed as Prometheus gauge.
- Unit test: simulate 3 connection failures → verify circuit opens, data flagged stale.
- Unit test: simulate recovery → verify circuit closes, data resumes.

**Rollback:**
- Remove circuit breaker; restore unbuffered connection.

**Affected Files:**
- `src/agents/market_intel.py` (circuit breaker wrapper)
- `src/execution/circuit_breaker.py` (new — circuit breaker implementation)
- `src/monitoring/metrics.py` (circuit breaker gauge)

---

### T-014: Add Kill-Switch Integration Tests

| Field | Value |
|---|---|
| **F-Ref** | F-034 |
| **Component** | Testing |
| **Severity** | HIGH — zero integration coverage for critical safety component |

**AC:**
- Test: trigger kill switch via drawdown → verify flatten called with all open positions.
- Test: trigger kill switch via daily loss → verify flatten called.
- Test: kill switch persist → restart → restore → verify state preserved (`_triggered=True`, `_triggered_at` timestamp).
- Test: auto-reset (when enabled) → verify reset after cooldown.
- Test: manual override via HTTP → verify kill switch disarmed.
- Test: concurrent triggers → verify exactly one flatten.

**Rollback:**
- Remove test file (not a rollback risk).

**Affected Files:**
- `tests/test_kill_switch.py` (new — integration test suite)

---

### T-015: Add Reconciliation Drift Alarm Tests

| Field | Value |
|---|---|
| **F-Ref** | F-035 |
| **Component** | Testing |
| **Severity** | HIGH — zero integration coverage for drift detection |

**AC:**
- Test: broker position differs from local → verify `DRIFT_DETECTED` event emitted.
- Test: broker fallback URL (paper) → verify graceful degradation.
- Test: reconciliation timeout → verify warning log + continue.
- Test: zero drift → verify no alarm.

**Rollback:**
- Remove test file.

**Affected Files:**
- `tests/test_reconciliation.py` (new)

---

### T-016: Add SL/TP Execution Tests

| Field | Value |
|---|---|
| **F-Ref** | F-036 |
| **Component** | Testing |
| **Severity** | HIGH — zero integration coverage for stop-loss/take-profit |

**AC:**
- Test: SL price triggered → verify market order created.
- Test: TP price triggered → verify limit order created (or market, per config).
- Test: trailing SL adjusts upward as price rises.
- Test: SL not triggered when price doesn't hit stop level.
- Test: multiple positions with same SL level → verify each triggers independently.

**Rollback:**
- Remove test file.

**Affected Files:**
- `tests/test_sl_tp.py` (new)

---

### T-017: Document Latency Budget

| Field | Value |
|---|---|
| **F-Ref** | F-037 |
| **Component** | Operations |
| **Severity** | HIGH — no SLAs for critical paths |

**AC:**
- Document contains:
  - Event bus delivery SLA (target: <10ms P99).
  - Order-to-fill latency budget (target: <500ms paper, <100ms live).
  - Kill-switch trigger-to-flatten latency budget (target: <1s).
  - Reconciliation latency budget (target: <5s full scan).
  - Metrics collection latency budget (target: <1s).
  - Profiling instructions: how to measure each budget with existing tooling.
- Document is in `docs/latency_budget.md`.

**Rollback:**
- Delete document.

**Affected Files:**
- `docs/latency_budget.md` (new)

---

### T-018: Create Disaster Recovery Runbook

| Field | Value |
|---|---|
| **F-Ref** | F-038 |
| **Component** | Operations |
| **Severity** | HIGH — no documented recovery procedures |

**AC:**
- Runbook covers:
  - SQLite corruption: detect, restore from backup, or rebuild from event store replay.
  - Event store failure: promote standby store, validate data integrity.
  - Broker API outage: kill switch procedure, manual position reconciliation.
  - System crash mid-order: detect incomplete orders on restart, reconcile.
  - Power loss: validate state on restart, replay events.
  - Docker container crash: docker-compose recovery steps.
  - Data loss scenario: restore from event store with point-in-time replay.
- Runbook lists contact info, escalation path.
- Runbook tested via dry-run procedure.
- Document is in `docs/disaster_recovery.md`.

**Rollback:**
- Delete document.

**Affected Files:**
- `docs/disaster_recovery.md` (new)

---

### T-019: Fix MIS→CO Upgrade

| Field | Value |
|---|---|
| **F-Ref** | F-024 |
| **Component** | Execution |
| **Severity** | HIGH — blanket CO upgrade without broker check |

**AC:**
- CO upgrade only applies when broker supports it (configurable per broker).
- If broker does not support CO, MIS order is placed as-is (intraday).
- Config flag: `enable_mis_to_co_upgrade: True/False` in broker config.
- Unit test: broker without CO support → MIS order stays MIS.
- Unit test: broker with CO support → MIS order upgraded to CO.

**Rollback:**
- Restore blanket CO upgrade.

**Affected Files:**
- `src/agents/execution.py` (broker capability check)
- `src/config/broker_config.py` (new or extend existing config)

---

### T-020: Fix TWAP Deletion Before Persist

| Field | Value |
|---|---|
| **F-Ref** | F-017 |
| **Component** | Execution (TWAP) |
| **Severity** | HIGH — TWAP state lost on crash after delete but before persist |

**AC:**
- TWAP order is persisted to event store before internal state is deleted.
- Delete operation is idempotent: `event_store.delete(order_id)` called before `_twap_orders.pop(order_id)`.
- Unit test: simulate crash after delete, before persist → verify TWAP state reconstructable from event store.

**Rollback:**
- Restore original delete-then-persist order.

**Affected Files:**
- `src/agents/execution.py` (reorder delete and persist operations)

---

## P2 — Medium (Should Fix, Next Sprint)

### T-021: Mark KafkaEventStore as Deprecated

| Field | Value |
|---|---|
| **F-Ref** | F-028 |
| **Component** | KafkaEventStore |
| **Severity** | MEDIUM — dead code with dependency |

- Add deprecation warning on import.
- Remove from factory default.
- Move to `src/event_store/_deprecated/`.

### T-022: Add Fast Path for ≤3 Strategies in PortfolioOptimizer

| Field | Value |
|---|---|
| **F-Ref** | F-029 |
| **Component** | PortfolioOptimizer |
| **Severity** | MEDIUM — scipy optimization overkill for 3 strategies |

- Add fast-path: if `n_strategies <= 3`, use equal-weight or risk-parity without scipy L-BFGS-B.
- Log which path was chosen.

### T-023: Add Human-in-the-Loop for ReflectionEngine Mutations

| Field | Value |
|---|---|
| **F-Ref** | F-026 |
| **Component** | ReflectionEngine |
| **Severity** | MEDIUM — auto-apply without review |

- Add `require_human_approval: True` flag (default).
- Mutations posted to a review queue; applied only after HTTP approval call.
- If no approval within configurable timeout, mutation is discarded.

### T-024: Remove/Flag Dead Dependencies

| Field | Value |
|---|---|
| **F-Ref** | F-030, F-031, F-032, F-033 |
| **Component** | Build / Docker |
| **Severity** | MEDIUM — dependency bloat |

- Flag broker stubs with `# TODO: remove once live broker connected`.
- Add comment in docker-compose that Redis is unused.
- Comment out PagerDuty integration unless `TRA_PAGERDUTY_ENABLED=True`.
- Remove Flink from `pyproject.toml` or move to deprecated extra.

### T-025: Add Market Data Backpressure

| Field | Value |
|---|---|
| **F-Ref** | F-039 |
| **Component** | MarketIntel |
| **Severity** | MEDIUM — OOM risk on burst |

- Add bounded queue between market data source and event bus.
- If queue full, drop oldest tick with counter increment.
- Prometheus gauge: `market_data_queue_fill_pct`.
- Documentation: how to size the queue based on expected tick rate.

### T-026: Add Trade Journal Export

| Field | Value |
|---|---|
| **F-Ref** | F-048 |
| **Component** | Operations |
| **Severity** | MEDIUM — no export, data locked in SQLite |

- Implement `python -m src.export.trade_journal [--format csv|json] [--from 2024-01-01]`.
- Export: all filled orders with timestamp, symbol, side, qty, price, fees, PnL.
- Include broker order ID, strategy name, tags.

### T-027: Add Credential Rotation Policy

| Field | Value |
|---|---|
| **F-Ref** | F-040 |
| **Component** | Security |
| **Severity** | MEDIUM — no rotation policy |

- Document rotation policy in `docs/security.md`.
- Add startup warning if any credential file is >90 days old.
- Support HashiCorp Vault as credential provider (optional).

---

## P3 — Low (Backlog — Nice-to-Have)

| Ticket | Summary | F-Ref |
|---|---|---|
| T-028 | Add configurable tax lot accounting (LIFO, HIFO) | F-043 |
| T-029 | Simulate order book depth (bid/ask) from paper data | F-045 |
| T-030 | Add position size validation against NSE lot size on flatten | F-025 |
| T-031 | Add market impact model to kill-switch flatten | F-023 |
| T-032 | Add fail-fast validation for event store schema | F-015 |

---

## Effort Summary

| Priority | Tickets | Estimated Effort |
|---|---|---|
| P0 | 4 | 3-5 days |
| P1 | 16 | 15-20 days |
| P2 | 7 | 8-10 days |
| P3 | 5 | 3-5 days |
| **Total** | **32** | **35-40 days** |

> Effort estimates are for a single developer familiar with the codebase.

## Rollback Strategy Summary

All P0 and P1 tickets include a specific rollback strategy. The general approach:
- **Single-commit per ticket** — each fix is a single commit for easy revert.
- **Feature flags** — risk-sensitive changes (margin check, rate limiting) are feature-flagged.
- **No data migration** — all changes are backward-compatible with existing event stores.
- **Test-first** — each ticket requires tests that pass before and after revert.
