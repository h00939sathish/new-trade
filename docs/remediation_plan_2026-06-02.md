# Trading Engine Remediation Plan

Audit source: `docs/trading_engine_audit_2026-06-02.md`

## Goal

Restore a trustworthy paper-trading path before any live-trading work. The first build slice is intentionally narrow: deterministic signal approval, deterministic paper execution, and no helper path that can submit an order before a local order-level risk gate.

## Phase 0: Make The Paper Path Runnable

1. Fix deterministic runtime exceptions in `RiskManagementAgent`, `ExecutionAgent`, and strategy signal code.
2. Repair regime transitions so a stable candidate regime can become the current regime and emit `system.state`.
3. Repair the full-system backtest agent-start patching so each patched agent keeps its own bound `start` method.
4. Run focused tests for risk, execution, regime detection, and undefined-name linting.

Exit gate: focused tests pass and the signal-to-risk-to-paper-fill flow can run without post-fill exceptions.

## Phase 1: Pre-Trade Risk Before Broker Calls

1. Add an internal order risk gate in execution before broker submission.
2. Apply that gate to approved signals, TWAP chunks, and direct `place_order()` helper calls.
3. Keep reduction-only exits allowed, but make that rule explicit and testable.
4. Emit rejected order events locally when the internal gate blocks an order.

Exit gate: a rejected order does not call the broker, and paper fills only occur for locally accepted orders.

## Phase 2: One Source Of Position Truth

1. Choose `PositionRegistry` as the in-process source of truth.
2. Route fills and broker reconciliation through it.
3. Update dependent portfolio and risk views from registry snapshots instead of independent mutable stores.
4. Remove or quarantine duplicate reconciliation logic after tests cover the chosen path.

Exit gate: one reconciliation run updates the same position state used by dashboard, risk, and execution.

## Phase 3: Live-Trading Interlock

1. Refuse live startup unless broker SDK, credentials, continuous order-status ingestion, authenticated controls, and kill-switch wiring are present.
2. Add continuous broker order and trade ingestion, including partial fills.
3. Authenticate FastAPI control endpoints and make emergency stop trigger the kill switch.
4. Fail closed when broker capabilities are missing.

Exit gate: live mode cannot start in a partially wired state.

## Phase 4: Profitability Evidence

1. Disable advanced/inert strategies from the active path.
2. Validate momentum, ORB, volatility compression, sideways reversion, and volatility breakout individually.
3. Run cost-aware walk-forward tests using clean historical data and explicit promotion gates.
4. Require paper burn-in with non-zero trades and zero unexplained reconciliation deltas before shadow-live testing.

Exit gate: strategy promotion is based on measured out-of-sample behavior, not synthetic fallback runs.

## Current Build Slice

This slice implements Phase 0 plus the first internal guard from Phase 1. It does not claim live readiness; continuous broker fill ingestion and authenticated dashboard controls remain separate work.
