# Phase 7: Build Plan

---

## Sprint 1: Critical Safety Fixes (Week 1)

### Sprint Goal
Eliminate all 6 CRITICAL findings — system can safely paper trade without misleading results.

| Task | Effort | Finding | Files |
|------|--------|---------|-------|
| **S1.1** Fix stat_arb config | 30min | F1 | `src/config/strategy_config.py:98` → set `"enabled": false` |
| **S1.2** Fix VaR false pass | 1hr | F2 | `src/risk/var.py:8` → raise RiskCheck failed when n<20 |
| **S1.3** Encrypt TOTP secret | 2hr | F3 | `src/utils/vault.py` + env var encryption hint |
| **S1.4** Add static IP validation | 1hr | F4 | `src/system.py` → pre-flight check at startup |
| **S1.5** Implement OAuth stub | 3hr | F5 | Integration with broker OAuth flows |
| **S1.6** Fix strategy weight normalization | 30min | F6 | `strategy_gen.py:_publish_signals` → exclude disabled |

### Definition of Done
- All 6 CRITICAL findings resolved
- Tests pass for fixed components
- Runtime verification confirms fixes

---

## Sprint 2: Paper Trading Quality (Week 2)

| Task | Effort | Finding |
|------|--------|---------|
| **S2.1** Clean stale TWAP orders on startup | 1hr | F7 |
| **S2.2** Add probabilistic partial fills to paper model | 3 days | F8 |
| **S2.3** Add market impact integration | 2 days | F9 |
| **S2.4** Fix kill switch Railway persistence | 1hr | F10 |
| **S2.5** Auto-update NSE lot sizes | 1hr | F11 |
| **S2.6** Remove ifconfig.me IP leak | 1hr | F12 |

---

## Sprint 3: Rate Limiting & Performance (Week 3)

| Task | Effort | Finding |
|------|--------|---------|
| **S3.1** Implement token bucket order throttle (8 OPS) | 2 days | F14 |
| **S3.2** Reduce Angel LTP poll rate to 5s | 1hr | F15 |
| **S3.3** Offload numpy to ThreadPoolExecutor | 2 days | Perf |
| **S3.4** Add Yahoo Finance rate limit handling | 1hr | Perf |
| **S3.5** Wire latency tracer | 1hr | F28 |
| **S3.6** Wire strategy decay auto-disable | 2 days | F24 |

---

## Sprint 4: Monitoring & Observability (Week 4)

| Task | Effort | Finding |
|------|--------|---------|
| **S4.1** Add event drop audit trail | 2 days | F19 |
| **S4.2** Add event deduplication | 1 day | F20 |
| **S4.3** Implement credential access audit log | 1 day | F30 |
| **S4.4** Add state database backup | 2 days | F29 |
| **S4.5** Improve MetricsStore counter restore | 1 day | F31 |

---

## Sprint 5: Backtest Quality (Week 5-6)

| Task | Effort | Finding |
|------|--------|---------|
| **S5.1** Add spread-aware fill model to backtest | 2 weeks | F16 |
| **S5.2** Add corporate action support | 1 week | F17 |
| **S5.3** Add walk-forward grids for all active strategies | 2 days | F21 |
| **S5.4** Add cross-validation to grid optimizer | 2 days | F22 |
| **S5.5** Improve MC validator with block bootstrap | 2 days | F23 |

---

## Sprint 6: ML & Advanced Features (Week 7-8)

| Task | Effort | Finding |
|------|--------|---------|
| **S6.1** Either build meta labeling pipeline or remove stub | 2 weeks | F18 |
| **S6.2** Wire HRP allocator into portfolio agent | 2 days | F25 |
| **S6.3** Wire alternative data RSS into sentiment signal | 2 days | F27 |

---

## Sprint 7: Security & Compliance (Week 8-9)

| Task | Effort | Finding |
|------|--------|---------|
| **S7.1** Implement full OAuth for all brokers | 5 days | F5 |
| **S7.2** Add secrets vault (HashiCorp Vault / Ansible Vault) | 3 days | F3 |
| **S7.3** Implement 5-year audit trail retention | 3 days | Compliance |
| **S7.4** Conduct formal pre-live system audit | 2 days | Compliance |

---

## Effort Summary

| Sprint | Effort | Findings |
|--------|--------|----------|
| Sprint 1: Critical Fixes | ~8 hours | 6 CRITICAL |
| Sprint 2: Paper Quality | ~7 days | 6 HIGH |
| Sprint 3: Rate Limiting | ~5 days | 3 HIGH + 3 MED |
| Sprint 4: Observability | ~5 days | 5 MED |
| Sprint 5: Backtest | ~17 days | 5 MED-HIGH |
| Sprint 6: ML/Advanced | ~16 days | 3 MED |
| Sprint 7: Security | ~11 days | 2 CRITICAL + compliance |
| **Total** | **~60 days** | **All findings** |

### Parallelizable Workstreams
- Sprint 1 (Critical) blocks everything — must go first
- After Sprint 1: Sprint 2 + Sprint 3 can run in parallel
- Sprint 4 can start after Sprint 3 (monitoring needs rate limiting)
- Sprint 5 independent of Sprints 2-4
- Sprint 6 independent (ML is isolated)
- Sprint 7 can start after Sprint 1 (security independent)

### Minimum Viable Production (MVP) Path
- Complete Sprint 1 (must-have for safety)
- Complete Sprint 2 items S2.1, S2.2, S2.4 (paper quality)
- Complete Sprint 3 items S3.1, S3.2 (rate limiting)
- **Total for MVP**: ~2 weeks

### Full Production Path
- All 7 sprints = ~8-9 weeks full-time
- With parallel execution (Sprint 2 + 3 simultaneously): ~6 weeks
