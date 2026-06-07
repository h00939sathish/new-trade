# Documentation Index

> **Last updated**: 2026-06-07
>
> This index lists every Markdown document in the `docs/` directory
> and the project root. Documents are grouped by purpose. Each entry
> has a 1-line description. For the *plan* that defines what we are
> building, see `.omo/plans/complete-audit-remediation.md`.

---

## Plans & Roadmap (project root)

| Doc | Purpose |
|---|---|
| [plan.md](../plan.md) | Post-audit (2026-06-02) paper-run plan; source of truth for the 5-day paper burn-in gate |
| [init.md](../init.md) | Project overview, tech stack, conventions, getting started (rewritten 2026-06-07) |
| [CHANGELOG.md](../CHANGELOG.md) | Version history reconstructed from `git log` (52 commits, 2026-05-24 → 2026-06-07) |
| [SECURITY.md](../SECURITY.md) | Security policy + pending credential-scrub action (Task 1) |
| [.omo/plans/complete-audit-remediation.md](../.omo/plans/complete-audit-remediation.md) | 55-task audit remediation plan (8 waves + F1–F4), 143 KB / 3 585 lines |

---

## Live-trading Gate (read first when promoting paper → live)

| Doc | Purpose |
|---|---|
| [live_trading_gate.md](live_trading_gate.md) | P2.5 — promotion criteria from paper burn-in to live capital (no live order routing until this is signed off) |
| [PAPER_5D_LAUNCH.md](PAPER_5D_LAUNCH.md) | Phase 1 gate — 5-day paper run launch checklist (current burn-in started 2026-06-05) |
| [active_strategy_set.md](active_strategy_set.md) | Active strategy set as of 2026-06-05: 3 active (momentum, sideways_reversion, vwap_reversion) + 2 filters; 9 disabled |
| [strategy_menu.md](strategy_menu.md) | Full strategy menu mapped from CodeTradingCafe research to this codebase |
| [remediation_plan_2026-06-02.md](remediation_plan_2026-06-02.md) | 2026-06-02 trading engine remediation plan (predecessor of the audit remediation plan) |

---

## Audits

| Doc | Purpose |
|---|---|
| [trading_engine_audit_2026-06-02.md](trading_engine_audit_2026-06-02.md) | Bottom-up audit of `src/agents/`, `src/risk/`, `src/execution/`; produced the 10-bug list (BUG-1 → BUG-10) |
| [delta_audit_post_stage1.md](delta_audit_post_stage1.md) | Stage 1 fixes vs prior audit claims (post-2026-06-05) |
| [backtest_audit.md](backtest_audit.md) | Backtester audit (2026-06-05) — surfaced the `SyncEventBus` event-ordering bug fixed in commit `59f1ac1` |
| [old_vs_new_comparison.md](old_vs_new_comparison.md) | Old `TRADE/` system vs new `new-trade` system (why we rebuilt) |

---

## Research

| Doc | Purpose |
|---|---|
| [backtest_data_providers_research.md](backtest_data_providers_research.md) | Survey of free backtest data providers for NSE 1m / 30m (Yahoo, jugaad-data, etc.) |
| [strategy_research_10.md](strategy_research_10.md) | 10-item strategy research roadmap (CodeTradingCafe review, gaps) |
| [strategy_scoring_better_alternatives.md](strategy_scoring_better_alternatives.md) | Strategy scoring rubric and better-alternatives matrix |

---

## Planned (Wave 2 audit remediation — will be created)

These docs are scheduled for creation by the audit remediation
plan (see `.omo/plans/complete-audit-remediation.md` Wave 2). They
do not exist yet; this index will be updated as each ships.

| Doc | Plan Task | Purpose |
|---|---|---|
| `docs/ARCHITECTURE.md` | Task 10 | Real Python architecture: agent responsibilities, event flow, storage backends, broker selection |
| `docs/RUNBOOK.md` | Task 11 | Day-to-day operator runbook: start/stop, log checks, kill-switch procedure |
| `docs/CONTRIBUTING.md` | Task 12 | Dev guide: setup, lint, test, add a strategy, add a connector |
| `docs/OPERATIONS.md` | Task 13 | Deploy / monitor / recover procedures (Railway, Docker, alerts) |

---

## Conventions

- **All paths in this index are relative to the repo root** unless
  prefixed with `../`.
- **Plan-numbered tasks** (e.g., Task 10) refer to entries in
  `.omo/plans/complete-audit-remediation.md`.
- **Commit hashes** in other docs (e.g., `59f1ac1`) are the
  short-SHA of the commit that introduced the change; verify with
  `git log --oneline | grep <hash>`.
- **"Wave N"** refers to the 8-wave grouping in the audit
  remediation plan; the plan also has a final F1–F4 verification
  wave.

---

## How to keep this index current

When you add a new `.md` file under `docs/`:

1. Add a row in the appropriate category table above.
2. Add a 1-line description that distinguishes the new doc from
   existing entries (avoid duplication).
3. If the doc is a *replacement* (e.g., `init.md` rewrite), update
   the `Last updated` date at the top.
4. If the doc is a *plan-derived* deliverable, reference the plan
   task number.
