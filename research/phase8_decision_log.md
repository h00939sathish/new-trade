# Phase 8: Decision Log

---

## Key Decisions Made During Investigation

| # | Decision | Rationale | Alternatives Considered | Made By | Date |
|---|----------|-----------|------------------------|---------|------|
| D01 | **Phase gate enforcement**: N+1 only after Phase N ledger closed | Ensures no finding slips between phases; foundational for RIGOR | Loose coupling (skip ahead) — rejected because contradictions depend on earlier findings | AI-assisted | 2026-06-30 |
| D02 | **Evidence Quality Ladder** (A=code, B=doc, C=external, D=speculative) | Prevents speculation from polluting findings; all findings must be grounded | Single tier — rejected because Phase 4 (online research) requires external sources | AI-assisted | 2026-06-30 |
| D03 | **stat_arb finding elevated to CRITICAL** despite appearing minor | Causes cascade of 4 runtime divergences; undermines strategy weight integrity | MEDIUM — rejected because it affects ALL active strategy allocations | AI-assisted | 2026-06-30 |
| D04 | **Kill-switch persistence corrected** (previously claimed "not persisted") | Direct code evidence shows file persistence | — | AI-assisted | 2026-06-30 |
| D05 | **Railway deploy caveat added** to kill-switch finding | Though persisted locally, Railway ephemeral FS loses state on deploy | Ignore deployment context — rejected because Railway is production deployment target | AI-assisted | 2026-06-30 |
| D06 | **No-go for live trading** despite paper trading working | 6 CRITICAL security/compliance issues prevent regulatory compliance | Go-live with caveats — rejected because static IP and OAuth are hard blockers (orders rejected) | AI-assisted | 2026-06-30 |
| D07 | **Paper trading CAN continue** with current issues | Risk findings don't affect paper mode; system functions correctly for simulation | Halt all trading — rejected because paper trading collects valuable burn-in data | AI-assisted | 2026-06-30 |
| D08 | **ML meta labeling flagged as MEDIUM** despite being a complete stub | Unused code has no runtime impact; cost of building vs. removing is decision for operator | CRITICAL — rejected because it affects nothing | AI-assisted | 2026-06-30 |
| D09 | **Static IP and OAuth called CRITICAL** not HIGH | External mandate (SEBI/NSE) with April 2026 deadline — orders literally rejected without these | HIGH — rejected because non-compliance = system can't trade | AI-assisted | 2026-06-30 |
| D10 | **Build plan structured as 7 sequential sprints** with parallelization notes | Clean dependency chain; Sprint 1 (critical fixes) must block all else | Single mega-sprint — rejected because testing/dependency chain is too tight | AI-assisted | 2026-06-30 |

## Open Decisions (Requiring Human Judgment)

| # | Question | Options | Recommendation | Needed By |
|---|----------|---------|---------------|-----------|
| UD01 | Build ML meta labeling or remove stub? | (a) Build pipeline (months of work) / (b) Remove dead code (<1hr) | Remove for now; revisit after production | Not urgent |
| UD02 | Continue with Angel One or switch to Kite-only? | (a) Fix Angel compliance issues / (b) Use Kite as primary / (c) Keep both | Keep both; diversify broker risk | Before Sprint 7 |
| UD03 | Host on Railway or VPS with persistent storage? | (a) Railway (current) + volume mount / (b) Dedicated VPS / (c) Both | Dedicated VPS for production; Railway for dev | Before Sprint 2 |
| UD04 | Paper trading budget for burn-in? | (a) ₹1L / (b) ₹5L / (c) ₹10L | Start with ₹1L paper; scale after 30 days | Before paper start |
| UD05 | Which strategies to prioritize for live trading? | (a) All 3 active / (b) Momentum only / (c) Momentum + VWAP | Start with momentum-only; add VWAP after 2 weeks | Before go-live |

## Decision Flow

```
All CRITICAL findings resolved? → No → NO-GO for live
  ↓ Yes
All HIGH findings resolved? → No → Continue paper + fix HIGH
  ↓ Yes
30-day paper burn-in complete? → No → Wait for burn-in
  ↓ Yes
Security audit passed? → No → Fix audit issues
  ↓ Yes
Scorecard ≥ 80%? → No → Address gaps
  ↓ Yes
→ GO for live trading
```
