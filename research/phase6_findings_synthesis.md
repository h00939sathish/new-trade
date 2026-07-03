# Phase 6: Findings Synthesis + Cost of Wrongness + Go/No-Go

---

## 1. All Findings Consolidated (from Phases 0-5)

### CRITICAL (6 findings)

| ID | Finding | System | Evidence | Fix Cost |
|----|---------|--------|----------|----------|
| F1 | stat_arb ACTIVE despite docs claiming disabled | Strategy Engine | TiA: config + runtime | <1hr |
| F2 | VaR passes insufficient data silently | Risk | TiA: code logic | <1hr |
| F3 | TOTP secret stored in plaintext (env var) | Security | TiA: angel client | <1hr |
| F4 | Static IP not registered for any broker | Security | TiA: no code; CP: external mandate | 1-2 days |
| F5 | No OAuth authentication (SEBI mandate) | Security | TiA: password auth; CP: SEBI circ | 3-5 days |
| F6 | Strategy weights diverge from config values | Strategy | TiA: runtime measurement | <30min |

### HIGH (12 findings)

| ID | Finding | System | Fix Cost |
|----|---------|--------|----------|
| F7 | Stale TWAP orders persist across restarts (13 rejected events/startup) | Execution | <1hr |
| F8 | Paper fill model lacks partial fills | Execution | 2-3 days |
| F9 | No market impact in paper fills | Execution | 1-2 days |
| F10 | Kill switch state lost on Railway deploy | Risk | <1hr (volume mount) |
| F11 | NSE lot sizes hardcoded with expiry dates — will go stale | Risk | <1hr |
| F12 | Angel IP leak via ifconfig.me | Security | <1hr |
| F13 | Kite access token never refreshed | Security | <1hr |
| F14 | No order rate limiting (10 OPS risk) | Performance | 1-2 days |
| F15 | Angel LTP polling exceeds rate limits | Performance | <1hr |
| F16 | Backtest uses paper fills not historical spreads | Backtest | 2-4 weeks |
| F17 | No corporate actions in backtest | Backtest | 1-2 weeks |
| F18 | ML meta labeling is a complete stub | ML | N/A (unused) |

### MEDIUM (10 findings)

| ID | Finding | System | Fix Cost |
|----|---------|--------|----------|
| F19 | Event bus drops events without audit trail | Event Bus | 1-2 days |
| F20 | No event deduplication | Event Bus | 1 day |
| F21 | Backtest walk-forward only for 3/14 strats | Backtest | 1-2 days |
| F22 | Grid optimizer has no overfitting protection | Backtest | 2-3 days |
| F23 | MC validator destroys temporal autocorrelation | Validation | 1-2 days |
| F24 | Strategy decay detector actions unwired | Analytics | 1-2 days |
| F25 | HRP allocator not wired into portfolio | Portfolio | 1-2 days |
| F26 | Groww connector is dead code | Connectors | <1hr |
| F27 | Alternative data RSS not consumed | Connectors | <30min |
| F28 | Latency tracer unwired | Monitoring | <1hr |

### LOW (5 findings)

| ID | Finding | System | Fix Cost |
|----|---------|--------|----------|
| F29 | No backup of state databases | All | 1-2 days |
| F30 | No audit log of credential access | Security | 1 day |
| F31 | Counter restore on MetricsStore restart is best-effort | Monitoring | 1 day |
| F32 | SyncEventBus nested deferral untested beyond 2 levels | Backtest | <1 day |
| F33 | Paper mode silent degradation (no alert on credential failure) | Security | <1 day |

## 2. Cost of Wrongness

For each critical finding, what is the financial/reputational cost of being wrong?

| Finding | If Ignored | Worst-Case Cost | Probability | Expected Loss |
|---------|-----------|----------------|:-----------:|:-------------:|
| **F1** stat_arb rogue | stat_arb generates opposing signals, reduces win rate 5-10% | ₹5,000/day (on ₹1L daily turnover) | 100% | ₹5,000/day |
| **F2** VaR false pass | Market opens with gap move, position exceeds risk limits | ₹50,000+ in a single gap move | 30% (1/3 months) | ₹15,000/month |
| **F3** TOTP plaintext | Env leak → permanent broker account compromise | Full account loss (₹5L+) | 5% (low but severe) | ₹25,000 |
| **F4** No static IP | All live orders rejected — system cannot trade | Trading impossible | 100% (from Apr 2026) | Complete loss of system utility |
| **F5** No OAuth | Broker discontinues legacy auth, system locked out | Trading impossible | 100% (SEBI mandate) | Complete loss of system utility |
| **F6** Wrong weights | Capital misallocated, 30% lower risk-adjusted return | ₹3,000/day opportunity cost | 100% | ₹3,000/day |

**Total expected monthly loss from ignoring CRITICAL findings**: ~₹23,000/month + existential risk of system inoperability.

## 3. Go/No-Go Recommendation

### Verdict: **NO-GO for Live Trading** ❌

The system fails 0/6 CRITICAL security/compliance checks required for live trading.

### Minimum Requirements to Go-Live
1. ✅ Register static IP with Angel One and Kite Connect
2. ✅ Implement OAuth authentication flow
3. ✅ Fix stat_arb config (disable or acknowledge)
4. ✅ Fix VaR false-pass on insufficient data
5. ✅ Encrypt or vault TOTP secrets
6. ✅ Add order rate limiting (≤10 OPS)
7. ✅ Complete 30-day paper trading burn-in (in progress)

### Conditions for Paper Trading Continuation ⚠️
Paper trading can continue with current issues. Recommended fixes before extended paper trading:
1. Fix stale TWAP order cleanup (F7) — noise-free startup
2. Add partial fills to paper model (F8) — realistic attribution
3. Wire latency tracer (F28) — performance baseline
4. Add strategy decay auto-disable (F24) — safety net

### Recommended Timeline
| Milestone | Date | Criteria |
|-----------|------|----------|
| Fix CRITICAL findings | Week 1-2 | All 6 CRITICAL resolved |
| Complete paper burn-in | 30 continuous days | Jan-Feb 2027 |
| Pre-live security audit | Week 4 | Pass security checklist |
| Go-live decision | After 30-day paper | Phase 9 scorecard ≥ 80% |
