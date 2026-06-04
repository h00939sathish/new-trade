# Three-Stage Roadmap — new-trade

Generated 2026-06-04. Built on the verification audit. Every task in
Stage 2 and Stage 3 is blocked on Stage 1 completing successfully.

---

## STAGE 1 — MAKE THE SYSTEM TRADE

**Goal**: One complete paper trade. ONE.

```
Signal → Risk Approval → Order → Fill → Position → Exit → PnL
```

**Success criteria**: at least one (BUY → FILL → SELL → FILL → PnL) cycle observed end-to-end.

**Non-goals**: live trading, attribution, regime filter, optimization.

### P0.1 Fix `passed` scope bug in `execution.py`

- **File**: `src/agents/execution.py`, method `_handle_risk_check`
- **Change**: move `passed = event.data.get("passed", False)` to the top of the function (before the `if check_name == "order_validation"` branch)
- **Why**: the line at 439 references `passed` before line 456 defines it → UnboundLocalError on every order_validation event
- **Verify**:
  - Reproduction script from audit prints "OK: order_validation flow did not crash"
  - `pytest tests/test_live_safety.py -q` still green

### P0.2 Fix `_capital` initialization in `risk_mgmt.py`

- **File**: `src/agents/risk_mgmt.py`, method `__init__`
- **Change**: add `self._capital = settings.reflection_initial_capital`
- **Why**: `_validate_order` reads `self._capital` at line 216 but the attribute was never set
- **Verify**:
  - Reproduction script with `ORDER_PROPOSED` event does not raise
  - `pytest tests/test_risk_mgmt_phase2.py -q` still green

### P0.3 Bypass EMA200 warm-up for the first-trade test

- **File**: `src/strategies/opening_range_breakout.py` and any other strategy that uses `EMA200Filter`
- **Change**: pass `bypass_warmup=True` from a test-only config so we can prove execution before 12:40 IST
- **Scope**: TEMPORARY. Removed in Stage 3 when we re-enable the real regime filter
- **Verify**: with this bypass, signal generation can start after 20 candles (~21 min), not 205

### P0.4 Trim active strategies to 3

- **File**: `src/config/strategy_config.py`, `DEFAULT_CONFIG`
- **Enabled**: `momentum`, `sideways_reversion`, `vwap_reversion` only
- **Disabled**: `tsmom`, `orb`, `vol_compression`, `vol_breakout`, `vwap_reversion` (the `__init__.py` ignore list already covers `pca_statarb`, `ml_regime`, `stat_arb`)
- **Verify**: `python -c "from src.agents.strategy_gen import StrategyGenAgent; ..."` registers exactly 3 strategies

### P0.5 Build controlled paper-run script

- **File**: `scripts/run_first_trade_paper.py`
- **Logic**:
  - Watchlist: RELIANCE only (deterministic)
  - Yahoo polling with 60s interval during IST market hours
  - Subscribe to `ORDER_CREATED`, `FILL`, `RISK_BREACH`
  - Exit on first complete round-trip OR 30 minutes OR 3 risk breaches
  - Log everything to `logs/first_trade_<timestamp>.jsonl`
- **Verify**: script completes without unhandled exception

### P0.6 Run during IST market hours

- IST market hours: Mon–Fri 9:15–15:30
- Run window: any weekday morning, target 9:30 IST start
- **Verify**: at minimum 1 BUY FILL and 1 SELL FILL observed in the log

### P0.7 Compute and verify PnL

- Read both fills from the JSONL log
- Compute: `(exit_price - entry_price) * qty - entry_commission - exit_commission`
- **Verify**: matches `portfolio_opt._pnl` from the last `PORTFOLIO_UPDATE` event
- **Verify**: `position_registry.get_quantity("RELIANCE")` is 0 after the second fill

**Stage 1 done when**: a single paper round-trip has been observed, the PnL arithmetic matches, and the position is closed.

---

## STAGE 2 — VERIFY POSITION TRUTH

**Goal**: collapse the two parallel position stores into one source of truth.

The audit found:
- `PortfolioOptimizationAgent._positions` (in-memory dict, drives dashboard and capital)
- `position_registry` (singleton, async-locked, drives risk_mgmt and strategy_gen)
- Both written on FILL by `portfolio.py:_on_fill`, no automated reconciliation
- Reconciliation is opt-in via `TRA_BURNIN=1`

### P1.1 Pick the source of truth

**Decision: `position_registry` becomes the SSOT.** Rationale:
- Already has async locking for writes
- Already used by `risk_mgmt` and `strategy_gen` for reads
- Designed for it (per its module docstring)
- `portfolio_opt._positions` becomes a derived view

### P1.2 Refactor `PortfolioOptimizationAgent` to read from `position_registry`

- **File**: `src/agents/portfolio.py`
- **Change**: in `_on_fill`, stop maintaining `_positions` directly. Instead, call `position_registry.update_from_fill(...)` (already done) and derive `get_position()` / `get_total_exposure()` from `position_registry.get_all_positions()`
- **Remove**: the duplicate `_positions` dict, the `total_bought`/`total_sold` tracking (not used downstream)
- **Keep**: `_pnl`, `_capital`, `_peak_capital` (these are aggregate portfolio state, not per-instrument)
- **Verify**: `pytest tests/test_portfolio.py -q` still green; `test_burnin_monitor.py` still green

### P1.3 Verify burn-in reconciliation is wired by default

- **File**: `src/main.py` or `src/system.py`
- **Change**: when `TRA_BURNIN=1`, the burn-in loop should run automatically (it does). When not set, the two-store drift cannot be detected. Either: (a) run the reconciliation in a low-rate always-on loop, or (b) keep it opt-in but document that fact.
- **Recommendation**: (a). Run a 5-minute reconciliation loop in paper mode by default. The cost is ~1ms per cycle.
- **Verify**: `state/burnin/reconciliation.jsonl` is updated on every Railway run

### P1.4 Add a position-drift alarm

- **File**: `src/agents/reconciliation.py` (extend the agent)
- **Logic**: subscribe to `FILL` events. After each FILL, compare `position_registry` to `portfolio_opt._positions`. If mismatch, emit `RISK_BREACH`.
- **Verify**: simulation test where two writes happen out-of-order produces an alert

**Stage 2 done when**: there is exactly one position store (`position_registry`), all reads go through it, and any drift is detected and alerted within 5 minutes.

---

## STAGE 3 — PROVE PROFITABILITY

**Goal**: enable 30-day paper trading with real performance measurement.

**Preconditions**: Stage 1 success AND Stage 2 SSOT in place.

### P2.1 Re-enable EMA200 regime filter

- Remove the `bypass_warmup=True` from P0.3
- Add back `ema200_regime_gate` and `adx_regime_filter` as filters (weight=0)
- **Verify**: cold-start math: 205 candles × 60s = 3.4h. First signal window opens at ~12:39 IST. Document this in `docs/active_strategy_set.md`.

### P2.2 Strategy attribution

- **File**: new `src/analytics/attribution.py` and extend `portfolio.py`
- **Per fill, record**:
  - strategy name (already on `FILL` event as `strategy` field)
  - realized PnL (already computed)
- **Aggregate**:
  - Per-strategy: total PnL, Sharpe, profit factor, expectancy
  - Per-strategy per-day: signal count, fill count, win rate, avg PnL
- **Output**: `logs/attribution_<date>.jsonl` updated at end of each day
- **Verify**: after a multi-day paper run, the JSONL contains meaningful numbers

### P2.3 Strategy decay detector

- **File**: extend `src/monitoring/decay_detector.py`
- **Trigger**: rolling 20-trade window's Sharpe < 0 → emit `STRATEGY_DECAY` event
- **Action**: not auto-disable, but emit and the alert agent notifies
- **Verify**: simulated losing streak triggers an alert

### P2.4 30-day paper run

- Run the system continuously during market hours for 30 trading days
- Daily checklist:
  - At least 1 closed trade per day
  - Reconciliation clean
  - No unhandled exceptions
  - Attribution data written
- **Verify**: 30 days of data, attribution readable, drawdown within `kill_switch_max_drawdown_pct`

### P2.5 Gate check: live trading

- After 30 days, evaluate:
  - Expectancy > 0 after costs (Sharpe-adjusted)
  - Max drawdown < 5%
  - Win rate consistent with strategy backtests
- If green: `live_trading_enabled = True` is justified
- If red: go back to Stage 3.1 and iterate on the strategy set

**Stage 3 done when**: 30 days of paper data is available, attribution shows whether the system has positive expectancy, and a defensible yes/no decision on live trading has been made.

---

## REMOVED FROM ROADMAP (per user direction)

These are NOT in any stage. The audit found them non-functional, unused, or premature for current scale:

- **Reflection Engine**: disabled, never activates. Code stays; runtime can stay disabled indefinitely. Revisit only if attribution (Stage 3) shows strategy needs dynamic retuning.
- **HMM regime classifier**: in `ignore_list`, file `src/core/regime/hmm_classifier.py` exists. Remove from runtime if not already.
- **TSMOM**: removed from active strategies in P0.4. Keep file for reference; do not enable.
- **Triple Barrier / Meta-labeling**: was in `DEFAULT_CONFIG` as `ml_regime` (disabled). No need to revive.
- **PCA stat arb**: already in `ignore_list`. No change.
- **HRP allocator**: `src/portfolio/hrp_allocator.py` exists, never used outside a stub. Remove or leave as dormant.
- **TWAP / Iceberg execution**: audit showed RuntimeError in test loop. Defer until the basic execution path proves itself.

---

## CRITICAL PATH

**Stage 1 (≤ 1 trading day)**: P0.1 → P0.2 → P0.3 → P0.4 → P0.5 → P0.6 → P0.7

**Stage 2 (≤ 1 day)**: P1.1 → P1.2 → P1.3 → P1.4

**Stage 3 (30 trading days)**: P2.1 → P2.2 → P2.3 → P2.4 → P2.5

Total: ~32 trading days from today.

---

## WHAT I WILL NOT DO

- Add new strategies
- Tune existing strategy parameters
- Add more alpha
- Add more notifiers
- Refactor for "scale"
- Speculate on future improvements
- Discuss TWAP, HMM, TSMOM, PCA, HRP, Triple Barrier, or Reflection Engine further

The job is to make one trade happen correctly, then prove the position state is honest, then measure whether the system makes money.
