# P2.5 — Live Trading Gate Check Criteria

This document defines the conditions under which `TRA_LIVE_TRADING_ENABLED` can be flipped from `false` to `true`. The criteria are evidence-based: each one is checked against actual data from the 30-day paper run, not theoretical.

## Prerequisites (must all be green)

- [x] Stage 1 P0.1 — `passed` scope bug in execution.py — **FIXED** (commit `ebdd65f`)
- [x] Stage 1 P0.2 — `_capital` initialization in risk_mgmt.py — **FIXED** (commit `ebdd65f`)
- [x] Stage 1 P0.4 — 3 active strategies — **DONE** (commit `ebdd65f`)
- [x] Stage 1 regime weight fix — multiplier-based — **FIXED** (commit `a1adaa4`)
- [x] Stage 2 P1.1 — SL trigger_price propagation — **FIXED** (commit `33a3ddb`)
- [x] Stage 2 P1.2 — Position SSOT enforcement — **FIXED** (commit `33a3ddb`)
- [x] Stage 2 P1.3 — Burn-in reconciliation default on in paper — **DONE** (this commit)
- [x] Stage 2 P1.4 — Position-drift alarm in reconciliation — **DONE** (this commit)
- [x] Stage 3 P2.1 — EMA200/ADX filters re-enabled — **DONE** (this commit)
- [x] Stage 3 P2.2 — Attribution aggregator — **DONE** (this commit, 9 tests pass)
- [x] Stage 3 P2.3 — Decay detector emits STRATEGY_DECAY — **DONE** (this commit, 3 tests pass, fixed scope bug in detector)

## 30-Day Paper Run Requirements

The system must run for **at least 20 trading days** in paper mode (allowing 10 days for weekends, holidays, or operational issues). Each day must satisfy:

### Daily Gate

- [ ] At least **1 closed trade** (BUY→FILL, SELL→FILL, realized PnL recorded) per day
- [ ] **Reconciliation clean** — no `position_drift` events in the day's logs
- [ ] **No unhandled exceptions** in the day's log files
- [ ] **Attribution data** written to `logs/attribution_<YYYY-MM-DD>.jsonl`
- [ ] **No `STRATEGY_DECAY` events** OR any decay event was actioned (strategy weight zeroed, alert sent)

If 5 or more days fail the daily gate, the run is suspended and the strategy set is reviewed.

### Aggregate Gate (over 20+ days)

- [ ] **Total realized PnL > 0** after all transaction costs
- [ ] **Sharpe ratio > 0.5** annualized (or as defined in `AttributionAggregator._rolling_sharpe`)
- [ ] **Max drawdown < 5%** of initial capital (₹1,000,000 × 5% = ₹50,000)
- [ ] **Win rate consistent with strategy backtests** — verify each strategy's win rate falls within ±20% of its backtested win rate
- [ ] **No position_drift events** during the entire run

## Operational Requirements

Beyond the gates, these operational items must be in place:

- [ ] **Live Kite credentials configured** in production `.env` (not just paper)
- [ ] **TRA_KITE_API_KEY**, **TRA_KITE_API_SECRET**, **TRA_KITE_ACCESS_TOKEN** all populated
- [ ] **TRA_LIVE_TRADING_ENABLED=false** in production `.env` until gate is passed
- [ ] **Risk limits reviewed**: max_position_size, max_drawdown, max_leverage, max_order — all set conservatively
- [ ] **Kill switch tested live**: simulate a drawdown, confirm kill switch triggers and cancels orders
- [ ] **Reconciliation with live broker tested**: confirm `reconcile_positions()` returns True at startup

## Decision Process

When the 20+ day run is complete:

1. Aggregate `logs/attribution_*.jsonl` files
2. Compute aggregate metrics: total PnL, Sharpe, max drawdown, win rate per strategy
3. Compare to the Aggregate Gate above
4. If ALL green: review with the user before flipping `TRA_LIVE_TRADING_ENABLED`
5. If ANY red: do not enable live trading; return to Stage 3 to iterate

## Risk: the live-trading flip is a one-way door

Live trading uses real money. Even a successful 30-day paper run is not a guarantee of live success. The user must explicitly approve the flip. This document is the checklist for that approval, not a self-approval.

## Status

- Daily gate: **PENDING** (awaiting 20 trading days of paper data)
- Aggregate gate: **PENDING**
- Operational requirements: **PARTIAL** (Kite credentials not yet configured for production)
- Decision process: **READY**

## Timeline

Paper run started: 2026-06-05 (this commit)
Earliest gate-check date: 2026-07-05 (20 trading days = ~30 calendar days)
Latest acceptable: 2026-08-05 (40 calendar days, accounting for holidays)
