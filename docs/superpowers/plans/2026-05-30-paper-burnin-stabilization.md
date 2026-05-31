# Paper Burn-In Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize CI and launch a monitored 24-hour Angel-data paper-trading burn-in.

**Architecture:** Preserve strategy API compatibility through re-exports, isolate Angel symbol
resolution behind a persistent cache, standardize dashboard build output, and add a paper-only
burn-in launcher with reconciliation snapshots. Keep live order routing disabled.

**Tech Stack:** Python 3.12, pytest, Ruff, mypy, SQLite/JSON state, Angel SmartAPI WebSocket,
FastAPI, Vite, PowerShell.

---

### Task 1: Restore Strategy Compatibility

**Files:**
- Modify: `src/agents/strategy_gen.py`

- [ ] Re-export strategy classes from `src.strategies.technical`.
- [ ] Run the five previously failing test modules and verify collection succeeds.

### Task 2: Add Angel Symbol Cache

**Files:**
- Create: `src/connectors/angel/symbol_index.py`
- Modify: `src/connectors/angel/client.py`
- Modify: `src/connectors/angel/__init__.py`
- Create: `tests/test_angel_symbol_index.py`

- [ ] Write failing tests for local load, refresh persistence, stale fallback, and lookup.
- [ ] Run the new tests and verify they fail because the symbol index does not exist.
- [ ] Implement the minimal persistent index.
- [ ] Delegate Angel client symbol loading to the index.
- [ ] Run Angel tests and verify they pass.

### Task 3: Align Dashboard Deployment Paths

**Files:**
- Modify: `dashboard/server.py`

- [ ] Serve built assets from `dashboard/dist`.
- [ ] Run the dashboard backend tests.
- [ ] Run `npm run build`.

### Task 4: Clear CI Gates

**Files:**
- Modify: Python files reported by Ruff and mypy.

- [ ] Run `ruff check src tests --fix`.
- [ ] Resolve remaining Ruff findings without unrelated refactors.
- [ ] Run `mypy src` and resolve type findings.
- [ ] Run the full Python test suite and resolve failures.
- [ ] Re-run Ruff, mypy, pytest, and the frontend build.

### Task 5: Add Paper Burn-In Launcher

**Files:**
- Create: `scripts/start_paper_burnin.ps1`
- Create: `scripts/check_paper_burnin.ps1`
- Create: `scripts/stop_paper_burnin.ps1`
- Modify: `src/main.py`

- [ ] Add a 30-minute local-paper reconciliation task and snapshot log.
- [ ] Add launcher, checker, and stop scripts.
- [ ] Start the paper burn-in with Kite credentials cleared.
- [ ] Confirm process liveness, `/health`, `/metrics`, and reconciliation snapshot.

### Task 6: Attach Thread Monitor

- [ ] Create a 30-minute heartbeat for 24-hour reporting.
- [ ] Report every check to this thread.
