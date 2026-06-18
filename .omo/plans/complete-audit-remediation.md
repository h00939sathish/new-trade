# Complete Audit Remediation — "new trade" Trading System
**Date:** 2026-06-07
**Audit Source:** `.omo/drafts/complete-audit-2026-06-07.md`
**Related:** `plan.md` (2026-06-02) — phases 2/3 partially overlap

---

## TL;DR

> **Quick Summary**: Fix 50+ issues across security, observability, testing, documentation, code quality, and operations — all surfaced in the 2026-06-07 audit. The existing `plan.md` Phase 1 is complete; this plan covers gaps in plan.md plus 30+ NEW findings from a fresh deep-read.
> 
> **Deliverables**:
> - Hardcoded secrets removed (Telegram chat ID, env URL); auth hardened
> - Stale `init.md`/`CHANGELOG.md` rewritten or deleted
> - `execution.py` 1377-line god-module split into 5 modules
> - In-memory metrics → persistent (SQLite) with daily PnL, exposure, drawdown metrics
> - Prometheus alerts expanded from 3 → 10+
> - State directory retention policy (no unbounded growth)
> - CI: gitleaks, pip-audit, Windows runner, dashboard build, coverage threshold
> - 6 new docs: ARCHITECTURE, RUNBOOK, CONTRIBUTING, OPERATIONS, docs/INDEX, POSTMORTEM_TEMPLATE
> - plan.md Phase 2 (profitability) tasks broken into executable units
> 
> **Estimated Effort**: XL (50+ tasks, 8 waves, ~3-6 months of focused work)
> **Parallel Execution**: YES — 8 implementation waves + 1 final verification wave
> **Critical Path**: Wave 1 (security) → Wave 6 (refactor execution.py) → Phase 2 broker reconciliation → Phase 3 → Final

---

## Context

### Original Request
User asked: "DO A COMPLETE AUDIT ON THIS PROJECT AND BUILD A PLAN ON WHAT IT LACKS AND DO THINGS WRONGLY."

### Audit Summary
- **Existing `plan.md` (2026-06-02)**: 10 bugs, 8 trading diagnosis, 3 phases, 5-day paper run in progress
- **NEW findings (2026-06-07 audit)**: 30+ additional issues not in plan.md, including:
  - Hardcoded Telegram chat ID in `monitor.py:7` (PII leak)
  - `init.md` describes fictional Rust/Go/Kafka architecture that doesn't exist
  - 12+ MyPy error codes disabled (effectively no type checking)
  - In-memory metrics wipe on restart (no 30-day history possible)
  - State files growing unbounded (35MB event DB, 26.6MB symbol JSON, 5 leaked test DBs)
  - Kill-switch singleton antipattern in `kill_switch.py:11-22`
  - Dashboard validation report is hardcoded placeholders (`dashboard/server.py:406-451`)
  - `dashboard/server.py` exposes `/api/kill-switch/reset` without auth if env var unset
  - `grafana` in compose has `admin/admin` password

### Metis Review
**Identified Gaps (addressed)**:
- Overlap with `plan.md` Phase 2/3 → explicit reference, not duplication
- 5-day paper run is concurrent → Wave 1-2 work must NOT break paper mode
- Windows dev environment → CI must include Windows runner, scripts must be cross-platform
- Single plan for 50+ tasks → use parallel waves aggressively

---

## Work Objectives

### Core Objective
Bring the trading system from "B- grade, paper-only, single-machine Windows dev" to "B+/A- grade, live-trading-ready, CI-enforced, runbook-documented" by fixing all P0-P2 audit findings, then executing `plan.md` Phases 2-3.

### Concrete Deliverables
- 30+ code/config files modified or created
- 5 new docs in `docs/` (ARCHITECTURE, RUNBOOK, CONTRIBUTING, OPERATIONS, INDEX)
- CHANGELOG.md fully updated
- 8 new Prometheus alerts
- 6+ new metrics exported
- CI expanded from 1 workflow to 1 workflow with 8+ checks
- `execution.py` split into 5 modules
- State retention policy implemented
- 30+ new tests added

### Definition of Done
- [ ] `pytest --cov=src --cov-fail-under=80` passes
- [ ] `ruff check` passes with no ignores
- [ ] `mypy --strict src/` passes
- [ ] `gitleaks detect` finds 0 secrets
- [ ] `pip-audit` finds 0 high/critical vulnerabilities
- [ ] All 8+ Prometheus alerts defined
- [ ] `docs/INDEX.md` exists and links all docs
- [ ] 30-day paper run gate criteria (`docs/live_trading_gate.md`) still pass after each wave

### Must Have
- All P0 security fixes (Telegram chat ID, auth enforcement, boto3 dep)
- All P1 hygiene fixes (CHANGELOG, init.md, state cleanup)
- Observability (persistent metrics, more alerts)
- CI hardening (gitleaks, pip-audit, coverage, Windows runner, dashboard build)
- execution.py split

### Must NOT Have (Guardrails)
- ❌ Do NOT break the 5-day paper run in progress (waves 1-2 are zero-downtime)
- ❌ Do NOT modify `plan.md` (it's the source of truth for the paper run gate)
- ❌ Do NOT introduce new broker credentials or live trading
- ❌ Do NOT add new strategies (just document and clean the existing 12)
- ❌ Do NOT delete `plan.md` or `init.md` (rewrite init.md, keep plan.md)
- ❌ Do NOT add Rust/Go/Kafka/Flink code (the architecture is Python-only by reality)
- ❌ Do NOT use `subprocess` for shell commands in Python (use `httpx`, `psutil`, etc.)

### Spec Framework Integration
- **Detected Framework**: None (no `openspec/`, `.specify/`, or `_bmad/` directory)
- This is a custom build; no spec framework commands to integrate

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, 329 passing tests)
- **Automated tests**: TDD where possible; tests-after for new features
- **Framework**: pytest with pytest-asyncio, pytest-cov
- **TDD workflow**: RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include Agent-Executed QA Scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend (Python)**: Use `Bash` (pytest) — run tests, assert pass, capture output
- **CLI scripts (PowerShell)**: Use `Bash` (pwsh) — execute, validate output, check exit code
- **API/Backend endpoints**: Use `Bash` (curl) — send requests, assert status + response fields
- **Config/Secrets**: Use `Bash` (gitleaks/pip-audit) — run, capture, assert clean
- **Docs**: Use `grep` + `Read` — verify all referenced files exist
- **Docker**: Use `Bash` (docker compose) — build, up, curl health, down

---

## Execution Strategy

### Parallel Execution Waves

> **5-8 tasks per wave target.** Fewer than 3 per wave (except final) = under-splitting.
> **Waves 1-2 are zero-downtime** — paper run must not break.

```
Wave 1 (P0 Security + Quick Wins — 6 tasks, ZERO DOWNTIME):
├── Task 1: Verify + complete git history scrub (SECURITY.md fix)
├── Task 2: Remove hardcoded Telegram chat ID + URL from monitor.py
├── Task 3: Add boto3 to pyproject.toml [vault] extra
├── Task 4: Enforce TRA_HTTP_AUTH_TOKEN in compose (no unset = 503)
├── Task 5: Fix Makefile db-up target (remove kafka reference)
└── Task 6: Update .gitignore to include .playwright-mcp/, graphify-out/, .tmp/

Wave 2 (Documentation Hygiene — 7 tasks, ZERO DOWNTIME):
├── Task 7: Rewrite init.md to match actual Python architecture
├── Task 8: Update CHANGELOG.md to reflect 45 days of work
├── Task 9: Create docs/INDEX.md linking all docs
├── Task 10: Create docs/ARCHITECTURE.md (real architecture)
├── Task 11: Create docs/RUNBOOK.md (operational guide)
├── Task 12: Create docs/CONTRIBUTING.md (dev guide)
└── Task 13: Create docs/OPERATIONS.md (deploy/monitor/recover)

Wave 3 (Test Quality + CI — 7 tasks):
├── Task 14: Add coverage threshold to pytest config (--cov-fail-under=80)
├── Task 15: Add gitleaks to CI workflow
├── Task 16: Add pip-audit to CI workflow
├── Task 17: Add ruff format --check to CI workflow
├── Task 18: Add Windows runner to CI workflow
├── Task 19: Add dashboard build step to CI workflow
└── Task 20: Add separate test isolation: tmp_path for DBs, remove leaked test DBs from state/

Wave 4 (Observability — 7 tasks):
├── Task 21: Persist MetricsCollector to SQLite (no more in-memory wipe)
├── Task 22: Add daily PnL, exposure, drawdown, open positions metrics
├── Task 23: Add per-strategy attribution metrics (trading_attribution_pnl_total)
├── Task 24: Add slippage, fill rate, broker API error metrics
├── Task 25: Expand prometheus_alerts.yml from 3 to 10+ alerts
├── Task 26: Add state file retention policy (auto-cleanup >30 days events)
└── Task 27: Wire dashboard /api/output/validation_report to real data (not placeholders)

Wave 5 (Code Quality — 7 tasks):
├── Task 28: Enable mypy strict mode (remove 12 disable_error_code)
├── Task 29: Add ruff B, C4, SIM, PT, TID rule sets
├── Task 30: Fix kill_switch __new__ singleton antipattern (lazy lock init)
├── Task 31: Fix execution.py system.py direct attribute access (force_paper_mode method)
├── Task 32: Fix execution.py _ORDER_DB_PATH to be configurable per env
├── Task 33: Fix settings.py eager secret loading (add reload() method)
└── Task 34: Add watchlist validation (dedup, format, min/max count)

Wave 6 (Refactor: Split execution.py God-Module — 7 tasks):
├── Task 35: Extract OrderRepository class from execution.py (DB CRUD)
├── Task 36: Extract PaperFillSimulator class from execution.py
├── Task 37: Extract TwapIcebergEngine class from execution.py
├── Task 38: Extract SignalQueue class from execution.py
├── Task 39: Extract ExecutionCore (orchestrator) from execution.py
├── Task 40: Update all callers (strategy_gen, risk_mgmt, reconciliation)
└── Task 41: Verify all 329 existing tests still pass after split

Wave 7 (plan.md Phase 2 — Profitability — 7 tasks):
├── Task 42: Implement broker reconciliation on startup
├── Task 43: Add backtest gate for ReflectionEngine mutations
├── Task 44: Add multi-timeframe confirmation (1m + 15m alignment)
├── Task 45: Replace 5bps flat slippage with depth-weighted model
├── Task 46: Add earnings calendar filter (block result day ±1)
├── Task 47: Add correlation filter (block if portfolio correlation >0.7)
└── Task 48: Wire stat_arb.py into StrategyGenAgent

Wave 8 (plan.md Phase 3 — Institutional — 7 tasks):
├── Task 49: Migrate event store to Postgres (concurrent readers)
├── Task 50: Add CNC/NRML product type support
├── Task 51: Add Prometheus alert: PagerDuty/Telegram on-call
├── Task 52: Add secret vault integration (HashiCorp Vault or AWS)
├── Task 53: Add microstructure signal (order flow imbalance)
├── Task 54: Add Kelly/fractional Kelly position sizing
└── Task 55: Add SEBI algo trading compliance review checklist

Wave FINAL (Verification — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
```

### Critical Path
1 → 4 → 21 → 22 → 25 → 35-39 → 42 → 49 → F1-F4 → user okay

### Parallel Speedup
~70% faster than sequential (especially Waves 4-6 with 7 parallel tasks each)

### Max Concurrent
7 (Waves 1, 2, 3, 4, 5, 6, 7, 8)

---

## Dependency Matrix (FULL)

- **1-13**: - - all other tasks, 1
- **1**:  - - 1 cleanup
- **2**: 1 - 2 fix
- **3**:  - - 3 add deps
- **4**: 1 - 4 enforce auth
- **5**:  - - 5 makefile
- **6**:  - - 6 gitignore
- **7-13**: 1 - 8, 9, 10, 11, 12, 13 docs (parallel, all depend on init.md understanding)
- **14**:  - - 14 cov threshold
- **15-20**: 14 - 21, 22, 23, 24, 25, 26 (CI work, parallel after coverage set)
- **21-24**: 15 - 27, 28, 29, 30, 31, 32, 33, 34 (metrics work, parallel)
- **25**: 21, 22, 23, 24 - 28+ (alerts need metrics)
- **26**:  - - 26 (state retention, independent)
- **27**: 21, 22, 23, 24 - 28+ (dashboard wiring needs metrics)
- **28-34**: 15, 17 - 35+ (code quality, parallel)
- **35-41**: 28, 29, 30, 31, 32, 33, 34 - 42+ (refactor after quality fixes)
- **42-48**: 35, 36, 37, 38, 39, 40, 41 - 49+ (Phase 2 after refactor)
- **49-55**: 42, 43, 44, 45, 46, 47, 48 - F1-F4 (Phase 3 after Phase 2)
- **F1-F4**: 1-55 - user okay

### Agent Dispatch Summary
- **Wave 1**: 6 tasks → `quick` (security hygiene, all small)
- **Wave 2**: 7 tasks → `writing` (docs are all writing)
- **Wave 3**: 7 tasks → `unspecified-high` (CI work, needs care)
- **Wave 4**: 7 tasks → `unspecified-high` (metrics + alerts, technical)
- **Wave 5**: 7 tasks → `unspecified-high` (code quality, refactor small)
- **Wave 6**: 7 tasks → `deep` (god-module split, careful work)
- **Wave 7**: 7 tasks → `deep` (Phase 2, profitability logic)
- **Wave 8**: 7 tasks → `deep` (Phase 3, institutional grade)
- **Final**: 4 tasks → `oracle` + `unspecified-high` + `unspecified-high` + `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**
> **FORMAT**: Task labels MUST use bare numbers: `1.`, `2.`, `3.` — NOT `T1.`, `Task 1.`, `Phase 1:`.

- [ ] 1. Verify and complete git history scrub of leaked credentials

  **What to do**:
  - Run `git log --all -p | grep -E "TRA_KITE|TRA_GROWW|TRA_ANGEL" | head` to verify the leak
  - If still present: install `git-filter-repo` and run `git filter-repo --invert-paths --path .env`
  - Also run `git filter-repo --replace-text expressions.txt` to scrub any inline patterns
  - Force-push to all remotes
  - Update `SECURITY.md` with verification result and timestamp
  - Add a `scripts/verify_no_secrets.sh` and `scripts/verify_no_secrets.ps1` to detect re-leaks

  **Must NOT do**:
  - Do NOT push without confirming force-push is safe (no collaborators)
  - Do NOT skip the verification grep

  **Recommended Agent Profile**:
  - **Category**: `quick` — script execution + verification
  - **Skills**: git, security
  - **Why**: Small focused task, well-defined steps

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 2-6 (security work may reveal more)
  - **Blocked By**: None

  **References**:
  - `SECURITY.md:1-87` — documents the leak and remediation
  - `docs/live_trading_gate.md:73-90` — post-audit recovery mentions this is partially done
  - `.githooks/pre-commit:11-26` — pattern scanner (won't catch history)

  **Acceptance Criteria**:
  - [ ] `git log --all -p | grep -E "TRA_KITE_API_KEY\s*="` returns NO matches with real values
  - [ ] `SECURITY.md` updated with "VERIFIED: history scrubbed on YYYY-MM-DD by [user]"
  - [ ] `scripts/verify_no_secrets.ps1` and `.sh` exist and exit 0
  - [ ] `git log --oneline | head -5` shows clean history post-scrub

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: History is clean of Kite credentials
    Tool: Bash (git)
    Preconditions: Repository has pushed remote
    Steps:
      1. cd "D:\projects\new trade"
      2. git log --all -p -- .env | grep -E "TRA_KITE_API_KEY\s*=\s*[a-zA-Z0-9]{16,}" || echo "CLEAN"
    Expected Result: "CLEAN" appears in output
    Failure Indicators: Any line with TRA_KITE_API_KEY= followed by 16+ alphanumeric chars
    Evidence: .omo/evidence/task-1-history-scrub-verified.txt

  Scenario: Verification scripts catch re-leaks
    Tool: Bash (pwsh)
    Preconditions: .env file exists with test secret
    Steps:
      1. pwsh scripts/verify_no_secrets.ps1
    Expected Result: Exit code 1 (detected the leak)
    Failure Indicators: Exit code 0 when .env contains secrets
    Evidence: .omo/evidence/task-1-verify-script-catches-leak.txt
  ```

  **Commit**: YES
  - Message: `chore(security): complete git history scrub of leaked credentials`
  - Files: `.gitignore`, `SECURITY.md`, `scripts/verify_no_secrets.{sh,ps1}`

- [ ] 2. Remove hardcoded Telegram chat ID and production URL from monitor.py

  **What to do**:
  - Add `MONITOR_CHAT_ID` and `MONITOR_API_URL` env var support to `monitor.py`
  - Move the existing `CHAT_ID = "8555799588"` to env (with empty default)
  - Move `API_URL = "..."` to env (with localhost default for dev)
  - If env vars are missing, log a clear error and exit 1 (not silent fail)
  - Add `os.environ.get("MONITOR_CHAT_ID", "")` validation (must be digits only)
  - Add a `--dry-run` flag to monitor.py for testing

  **Must NOT do**:
  - Do NOT keep the hardcoded values as fallback
  - Do NOT commit any new chat ID values

  **Recommended Agent Profile**:
  - **Category**: `quick` — small env-var extraction
  - **Skills**: python, security
  - **Why**: Trivial refactor, well-bounded

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: Task 1 (must scrub history first)

  **References**:
  - `monitor.py:7` — `CHAT_ID = "8555799588"` (the hardcoded value)
  - `monitor.py:6` — `API_URL = "https://new-trade-production.up.railway.app/api/paper-report"`
  - `monitor.py:177-188` — telegram token retrieval
  - `.env.example` — pattern for env vars

  **Acceptance Criteria**:
  - [ ] `monitor.py` contains no string literal for chat ID
  - [ ] `monitor.py` contains no `https://new-trade-production` URL
  - [ ] Both values come from env vars with documented defaults
  - [ ] Missing env var → clear error, exit 1
  - [ ] `grep "8555799588" monitor.py` returns nothing
  - [ ] `grep "new-trade-production" monitor.py` returns nothing

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: monitor.py fails clearly when env vars missing
    Tool: Bash (pwsh)
    Preconditions: MONITOR_CHAT_ID and MONITOR_API_URL unset
    Steps:
      1. Remove-Item Env:MONITOR_CHAT_ID -ErrorAction SilentlyContinue
      2. Remove-Item Env:MONITOR_API_URL -ErrorAction SilentlyContinue
      3. python monitor.py
    Expected Result: Exit code 1 with "ERROR: MONITOR_CHAT_ID not set" in stderr
    Failure Indicators: Exit code 0, or hardcoded value used as fallback
    Evidence: .omo/evidence/task-2-monitor-missing-env-error.txt

  Scenario: monitor.py uses env vars when set
    Tool: Bash (pwsh)
    Preconditions: Test env vars set
    Steps:
      1. $env:MONITOR_CHAT_ID="1234567890"
      2. $env:MONITOR_API_URL="http://localhost:8080/api/paper-report"
      3. python monitor.py --dry-run
    Expected Result: "DRY RUN" output, exit 0, no actual API call
    Failure Indicators: Actual API call to production URL
    Evidence: .omo/evidence/task-2-monitor-dry-run.txt
  ```

  **Commit**: YES
  - Message: `refactor(monitor): externalize hardcoded chat ID and API URL to env vars`
  - Files: `monitor.py`, `.env.example`

- [ ] 3. Add boto3 to pyproject.toml and split vault deps into [vault] extra

  **What to do**:
  - Add `boto3>=1.34` to a new `[vault]` optional-dependency group
  - Move the `vault_provider` setting to require explicit install of `[vault]` extra
  - Update `src/utils/vault.py` to raise a clear error if provider is set but boto3 is missing
  - Add `hvac>=2.0` for HashiCorp Vault (since `vault.py:9` references it)
  - Document in `pyproject.toml` and `docs/OPERATIONS.md`

  **Must NOT do**:
  - Do NOT add boto3 to main dependencies (most users don't need it)
  - Do NOT keep the silent ImportError catch in vault.py:59-60

  **Recommended Agent Profile**:
  - **Category**: `quick` — dependency addition
  - **Skills**: python, packaging
  - **Why**: Trivial pyproject edit + small code change

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/utils/vault.py:42` — `import boto3` (unconditional)
  - `src/utils/vault.py:59-60` — silent `ImportError` catch
  - `pyproject.toml:6-23` — main dependencies
  - `pyproject.toml:27-51` — optional-dependencies pattern

  **Acceptance Criteria**:
  - [ ] `pyproject.toml` has new `[vault]` optional-dependency with boto3, hvac
  - [ ] `pip install -e ".[vault]"` succeeds
  - [ ] `src/utils/vault.py` raises `RuntimeError` (not silent return) when boto3 missing but `TRA_VAULT_PROVIDER=aws`
  - [ ] `vault.py` raises `RuntimeError` when hvac missing but `TRA_VAULT_PROVIDER=vault`
  - [ ] `pytest tests/` still passes (no vault provider tests fail)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Vault raises clear error when provider set but boto3 missing
    Tool: Bash (pytest)
    Preconditions: vault extras NOT installed
    Steps:
      1. TRA_VAULT_PROVIDER=aws python -c "from src.utils.vault import load_secure_secret; print(load_secure_secret('TRA_FAKE_KEY'))"
    Expected Result: RuntimeError containing "boto3 not installed" and "[vault]" extra install hint
    Failure Indicators: Empty string returned silently
    Evidence: .omo/evidence/task-3-vault-missing-boto3-error.txt

  Scenario: Vault works after extras installed
    Tool: Bash (pip + pytest)
    Preconditions: Clean venv
    Steps:
      1. pip install -e ".[vault,dev]"
      2. pytest tests/ -k "vault" -v
    Expected Result: All vault tests pass
    Failure Indicators: ImportError or RuntimeError
    Evidence: .omo/evidence/task-3-vault-extras-installed-pass.txt
  ```

  **Commit**: YES
  - Message: `chore(deps): add [vault] extra with boto3 and hvac, raise clear errors when missing`
  - Files: `pyproject.toml`, `src/utils/vault.py`

- [ ] 4. Enforce TRA_HTTP_AUTH_TOKEN in docker-compose.yml (no unset = 503)

  **What to do**:
  - In `docker-compose.yml`, add `TRA_HTTP_AUTH_TOKEN` to `trading-app` service as a REQUIRED env var (no default)
  - Add a startup healthcheck that fails if the token is empty
  - Update `src/main.py` to log a WARNING on startup if token is empty (not silent)
  - Update `dashboard/server.py` to do the same
  - Add a `.env.compose.example` that documents how to generate a token: `openssl rand -hex 32`

  **Must NOT do**:
  - Do NOT remove the `if not token` branch in `_require_operator_auth` (it's correct)
  - Do NOT use a hardcoded token in compose

  **Recommended Agent Profile**:
  - **Category**: `quick` — config + small code change
  - **Skills**: docker, security
  - **Why**: Bounded config change

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `dashboard/server.py:83-97` — `_require_operator_auth` (current correct logic)
  - `main.py:48-69` — metrics_http_server auth (current correct logic)
  - `docker-compose.yml:52-71` — `trading-app` service
  - `audit draft 3.3` — analysis of auth gap

  **Acceptance Criteria**:
  - [ ] `docker-compose.yml` has `TRA_HTTP_AUTH_TOKEN: ${TRA_HTTP_AUTH_TOKEN:?TRA_HTTP_AUTH_TOKEN must be set}` pattern
  - [ ] `main.py` logs WARNING on startup if token empty
  - [ ] `dashboard/server.py` logs WARNING on import if token empty
  - [ ] `.env.compose.example` shows `openssl rand -hex 32` command
  - [ ] `docker compose config` fails without TRA_HTTP_AUTH_TOKEN set

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: docker-compose fails fast when token missing
    Tool: Bash (docker compose)
    Preconditions: TRA_HTTP_AUTH_TOKEN unset
    Steps:
      1. Remove-Item Env:TRA_HTTP_AUTH_TOKEN -ErrorAction SilentlyContinue
      2. docker compose config 2>&1 | Select-String "TRA_HTTP_AUTH_TOKEN"
    Expected Result: Error message "variable not set" or similar
    Failure Indicators: Successful config with empty token
    Evidence: .omo/evidence/task-4-compose-fails-no-token.txt

  Scenario: main.py warns on empty token
    Tool: Bash (pwsh)
    Preconditions: Empty TRA_HTTP_AUTH_TOKEN
    Steps:
      1. $env:TRA_HTTP_AUTH_TOKEN=""
      2. python -c "import src.main" 2>&1 | Select-String "WARNING.*TRA_HTTP_AUTH_TOKEN"
    Expected Result: WARNING line in output mentioning the token
    Failure Indicators: Silent startup
    Evidence: .omo/evidence/task-4-main-warns-empty-token.txt
  ```

  **Commit**: YES
  - Message: `feat(security): enforce TRA_HTTP_AUTH_TOKEN in compose, warn on empty`
  - Files: `docker-compose.yml`, `src/main.py`, `dashboard/server.py`, `.env.compose.example`

- [ ] 5. Fix Makefile db-up target (remove kafka reference, add only available services)

  **What to do**:
  - Read `docker-compose.yml` to identify which services exist (postgres, redis, prometheus, grafana, trading-app)
  - Update Makefile `db-up` to use only existing services
  - Add a `db-up-full` target that includes monitoring (prometheus, grafana)
  - Add a `db-up-minimal` target for just postgres + redis
  - Add `db-ps` to show running containers
  - Add `db-logs` to tail logs from trading-app

  **Must NOT do**:
  - Do NOT add a kafka service to compose (it's not in plan.md scope)
  - Do NOT remove the Makefile `Makefile` `db-up` target (just fix it)

  **Recommended Agent Profile**:
  - **Category**: `quick` — Makefile edit
  - **Skills**: make, docker
  - **Why**: Trivial, bounded

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `Makefile:17-21` — current db-up/db-down targets
  - `docker-compose.yml:1-76` — actual service list (postgres, redis, prometheus, grafana, trading-app)
  - `audit draft 2.3` — analysis of stale Makefile

  **Acceptance Criteria**:
  - [ ] `make db-up` succeeds without "no such service" error
  - [ ] `make db-up-minimal` brings up only postgres and redis
  - [ ] `make db-up-full` brings up everything including prometheus and grafana
  - [ ] `make db-ps` shows running containers
  - [ ] `make db-logs` tails trading-app logs
  - [ ] `make db-down` cleanly stops all services

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: db-up succeeds
    Tool: Bash (make + docker)
    Preconditions: Clean state
    Steps:
      1. make db-down 2>&1
      2. make db-up 2>&1
      3. docker compose ps --services
    Expected Result: All services listed, no "no such service" error
    Failure Indicators: Error about missing "kafka" service
    Evidence: .omo/evidence/task-5-make-db-up-success.txt

  Scenario: db-up-minimal brings up only required services
    Tool: Bash (make + docker)
    Preconditions: Clean state
    Steps:
      1. make db-down
      2. make db-up-minimal
      3. docker compose ps
    Expected Result: Only postgres and redis running
    Failure Indicators: Promtail, Grafana, or other services running
    Evidence: .omo/evidence/task-5-make-db-up-minimal.txt
  ```

  **Commit**: YES
  - Message: `fix(make): correct db-up target, add db-up-minimal and db-up-full variants`
  - Files: `Makefile`

- [ ] 6. Update .gitignore to include playwright, graphify, tmp, and other leak-prone artifacts

  **What to do**:
  - Read current `.gitignore` and compare against actual `Get-ChildItem -Force` output
  - Add any missing patterns: `.playwright-mcp/`, `graphify-out/`, `.tmp/`, `dash_stdout.txt`, `dash_stderr.txt`
  - Also add: `*.db-shm`, `*.db-wal` (SQLite WAL files, were missing)
  - Add a `state/` retention check: `state/angel_symbols.json` should be gitignored
  - Run `git check-ignore` on every file in `state/` to confirm none are tracked

  **Must NOT do**:
  - Do NOT remove the existing `.gitignore` entries (they're correct)
  - Do NOT add overly broad patterns (e.g., `*.json` would catch important configs)

  **Recommended Agent Profile**:
  - **Category**: `quick` — gitignore edit + verification
  - **Skills**: git
  - **Why**: Bounded config + verification

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `.gitignore:1-69` — current state
  - `audit draft 2.3` — list of leak-prone files

  **Acceptance Criteria**:
  - [ ] `.gitignore` includes `.playwright-mcp/`, `graphify-out/`, `.tmp/`
  - [ ] `.gitignore` includes `*.db-shm`, `*.db-wal`
  - [ ] `.gitignore` includes `state/angel_symbols.json`
  - [ ] `git check-ignore state/trading_events.db` returns 0 (ignored)
  - [ ] `git check-ignore state/order_state.db` returns 0 (ignored)
  - [ ] `git check-ignore .playwright-mcp/` returns 0 (ignored)
  - [ ] `git status` shows no untracked `state/*.db*` files

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: gitignore catches all leak-prone files
    Tool: Bash (git)
    Preconditions: Files exist
    Steps:
      1. foreach ($f in "state/trading_events.db", "state/order_state.db", "state/angel_symbols.json", ".playwright-mcp/test.log", "graphify-out/index.html", ".tmp/scratch.txt") {
           $result = git check-ignore $f 2>&1
           if ($LASTEXITCODE -ne 0) { Write-Host "NOT IGNORED: $f" }
         }
    Expected Result: All files report as ignored (no "NOT IGNORED" output)
    Failure Indicators: Any "NOT IGNORED:" line in output
    Evidence: .omo/evidence/task-6-gitignore-catches-all.txt
  ```

  **Commit**: YES
  - Message: `chore(gitignore): add missing patterns for playwright, graphify, tmp, db WAL files`
  - Files: `.gitignore`

- [ ] 7. Rewrite init.md to match actual Python-only architecture

  **What to do**:
  - Read current `init.md` to identify fictional claims
  - Rewrite it to describe the actual architecture: pure Python 3.12, event-sourced multi-agent, SQLite/Postgres/Kafka backends, 5 broker connectors, 12 strategies (3 active), React/FastAPI dashboard
  - Add: "This init.md was rewritten on 2026-06-07 to match the actual codebase. The original version described a planned Rust/Go/Kafka/Flink/K8s architecture that was never built."
  - Keep the original "Conventions" section (event sourcing, deterministic replay, etc.) as it's still valid
  - Add: link to `docs/ARCHITECTURE.md` for the real architecture doc
  - Update "Tech Stack" section to list actual deps from `pyproject.toml`

  **Must NOT do**:
  - Do NOT delete init.md (it's referenced in some test setup)
  - Do NOT add Rust/Go/Kafka claims even as future plans (use docs/ARCHITECTURE.md for that)

  **Recommended Agent Profile**:
  - **Category**: `writing` — technical doc rewrite
  - **Skills**: documentation, python
  - **Why**: Pure documentation task

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `init.md:1-57` — current fictional content
  - `pyproject.toml:6-51` — actual deps
  - `src/` directory listing — actual modules
  - `docs/ARCHITECTURE.md` (to be created in Task 10) — link target

  **Acceptance Criteria**:
  - [ ] `init.md` does not mention Rust, Go, Kafka, Flink, Feast, Ray, TimescaleDB, K8s, Istio
  - [ ] `init.md` describes the actual Python 3.12, event-sourced, multi-agent architecture
  - [ ] `init.md` has "Last updated: 2026-06-07" header
  - [ ] `init.md` is < 100 lines (down from 57 with corrections, target ~80)
  - [ ] All claims in init.md are verifiable in code (no fictional features)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: init.md no longer claims fictional architectures
    Tool: Bash (grep)
    Preconditions: init.md exists
    Steps:
      1. foreach ($term in "Rust", "Go", "Kafka", "Flink", "Feast", "Ray", "Kubernetes", "Istio") {
           $count = (Select-String -Path init.md -Pattern $term -SimpleMatch).Count
           if ($count -gt 0) { Write-Host "FOUND: $term ($count times)" }
         }
    Expected Result: No "FOUND:" lines
    Failure Indicators: Any mention of fictional tech
    Evidence: .omo/evidence/task-7-init-md-no-fictional-tech.txt

  Scenario: init.md describes actual stack
    Tool: Bash (grep)
    Preconditions: init.md exists
    Steps:
      1. foreach ($term in "Python 3.12", "Pydantic", "aiosqlite", "asyncio", "React", "FastAPI") {
           $count = (Select-String -Path init.md -Pattern $term).Count
           if ($count -eq 0) { Write-Host "MISSING: $term" }
         }
    Expected Result: No "MISSING:" lines
    Failure Indicators: Missing mention of actual tech
    Evidence: .omo/evidence/task-7-init-md-actual-stack-mentioned.txt
  ```

  **Commit**: YES
  - Message: `docs(init): rewrite to match actual Python-only architecture`
  - Files: `init.md`

- [ ] 8. Update CHANGELOG.md to reflect 45 days of work since last entry

  **What to do**:
  - Read current `CHANGELOG.md` (last entry 2026-05-23)
  - Reconstruct a timeline of major changes from 2026-05-23 to 2026-06-07:
    - Bug fixes BUG-1 to BUG-10 (all per plan.md)
    - Phase 1 paper run launched (2026-06-05)
    - Active strategy set (3 active, 3 disabled)
    - Credentials leak discovered and remediated (SECURITY.md)
    - 5-day paper run gates (live_trading_gate.md)
    - All 329 tests passing
  - Add new sections under [Unreleased]: 2026-06-02 (post-audit), 2026-06-05 (paper run), 2026-06-06 (credentials fix)
  - Use "Keep a Changelog" format

  **Must NOT do**:
  - Do NOT modify or remove the original Phase 1 entry
  - Do NOT add speculative future entries

  **Recommended Agent Profile**:
  - **Category**: `writing` — changelog curation
  - **Skills**: documentation, git
  - **Why**: Pure documentation, requires git log archaeology

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `CHANGELOG.md:1-64` — current stale state
  - `plan.md` — bug fix timeline
  - `docs/live_trading_gate.md:73-90` — recovery timeline
  - `git log --oneline --since="2026-05-23"` — actual commit history

  **Acceptance Criteria**:
  - [ ] CHANGELOG.md has entries for 2026-06-02 (post-audit), 2026-06-05 (paper run), 2026-06-06 (credentials)
  - [ ] Each new entry has Added/Changed/Fixed subsections
  - [ ] Total length grows by 30-80 lines (not 500+ bloat)
  - [ ] Original Phase 1 entry preserved
  - [ ] Follows "Keep a Changelog" format

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: CHANGELOG has all required dates
    Tool: Bash (grep)
    Preconditions: CHANGELOG.md exists
    Steps:
      1. foreach ($date in "2026-05-23", "2026-06-02", "2026-06-05", "2026-06-06", "2026-06-07") {
           $count = (Select-String -Path CHANGELOG.md -Pattern $date).Count
           if ($count -eq 0) { Write-Host "MISSING: $date" }
         }
    Expected Result: No "MISSING:" lines
    Failure Indicators: Any date missing
    Evidence: .omo/evidence/task-8-changelog-has-all-dates.txt
  ```

  **Commit**: YES
  - Message: `docs(changelog): update to reflect 45 days of work since 2026-05-23`
  - Files: `CHANGELOG.md`

- [ ] 9. Create docs/INDEX.md linking all docs

  **What to do**:
  - List all `.md` files in `docs/`
  - Group by category: Plans, Specs, Audits, Operations, Strategies, Live trading
  - Add a 1-line description for each
  - Order by recency (newest first)
  - Add a "Last updated" date at the top

  **Must NOT do**:
  - Do NOT link to non-existent docs
  - Do NOT add summaries (keep it as a pure index)

  **Recommended Agent Profile**:
  - **Category**: `writing` — pure documentation index
  - **Skills**: documentation
  - **Why**: Trivial curation

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `docs/` directory listing (all .md files)
  - `audit draft 7.4` — index requirement

  **Acceptance Criteria**:
  - [ ] `docs/INDEX.md` exists
  - [ ] Links to every `.md` file in `docs/`
  - [ ] Grouped by category (Plans, Audits, Operations, etc.)
  - [ ] 1-line description per doc
  - [ ] "Last updated: 2026-06-07" header

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: All docs are linked
    Tool: Bash (find + grep)
    Preconditions: docs/ exists
    Steps:
      1. $allDocs = Get-ChildItem docs -Recurse -Filter *.md | Select-Object -ExpandProperty FullName
      2. foreach ($doc in $allDocs) {
           $relPath = $doc.Replace("\", "/").Replace("docs/", "")
           $linked = Select-String -Path docs/INDEX.md -Pattern $relPath -SimpleMatch
           if (-not $linked) { Write-Host "NOT LINKED: $relPath" }
         }
    Expected Result: No "NOT LINKED:" lines
    Failure Indicators: Any unlinked doc
    Evidence: .omo/evidence/task-9-index-links-all-docs.txt
  ```

  **Commit**: YES
  - Message: `docs(index): create INDEX.md linking all docs`
  - Files: `docs/INDEX.md`

- [ ] 10. Create docs/ARCHITECTURE.md describing the real Python architecture

  **What to do**:
  - Read `src/` tree to map modules
  - Document: agent responsibilities and message flow
  - Document: event types (from `src/schemas/events.py`) and their lifecycles
  - Document: storage backend trade-offs (SQLite vs Postgres vs Kafka)
  - Document: broker selection logic (which broker is used when)
  - Document: state persistence (where each piece of state lives)
  - Add ASCII diagram of agent message flow
  - Link from `init.md` and `docs/INDEX.md`

  **Must NOT do**:
  - Do NOT claim Rust/Go/Kafka code exists
  - Do NOT duplicate plan.md (reference it)

  **Recommended Agent Profile**:
  - **Category**: `writing` — technical architecture doc
  - **Skills**: documentation, python, architecture
  - **Why**: Complex doc, needs understanding of system

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/agents/__init__.py` — agent exports
  - `src/agents/base.py` — BaseAgent
  - `src/schemas/events.py` — event types
  - `src/event_store/` — backends
  - `src/system.py` — orchestrator
  - `plan.md` — context

  **Acceptance Criteria**:
  - [ ] `docs/ARCHITECTURE.md` exists, 200-500 lines
  - [ ] Describes actual Python-only architecture
  - [ ] Has ASCII diagram of agent message flow
  - [ ] Lists all 12 strategies with active/disabled status
  - [ ] Lists all 5 broker connectors
  - [ ] Links to plan.md, init.md, security docs

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: ARCHITECTURE.md matches actual code
    Tool: Bash (grep)
    Preconditions: docs/ARCHITECTURE.md exists
    Steps:
      1. $strategies = Get-ChildItem src/strategies -Filter *.py | Select-Object -ExpandProperty BaseName
      2. foreach ($s in $strategies) {
           if (-not (Select-String -Path docs/ARCHITECTURE.md -Pattern $s -SimpleMatch)) {
             Write-Host "NOT MENTIONED: $s"
           }
         }
    Expected Result: No "NOT MENTIONED:" lines
    Failure Indicators: Missing strategy mention
    Evidence: .omo/evidence/task-10-architecture-covers-all-strategies.txt
  ```

  **Commit**: YES
  - Message: `docs(arch): create ARCHITECTURE.md describing actual Python architecture`
  - Files: `docs/ARCHITECTURE.md`

- [ ] 11. Create docs/RUNBOOK.md (operational guide)

  **What to do**:
  - Sections to include:
    - "What to do when kill switch fires at 2 PM"
    - "How to add a new instrument to the watchlist"
    - "How to rotate Kite access token (with restart)"
    - "How to recover from a stuck reconciliation"
    - "What to do if angel_symbols.json is missing or corrupt"
    - "How to debug a paper trade that didn't fire"
    - "How to read logs/runtime_traces/"
    - "How to interpret reconciliation.jsonl"
  - Each section: "Symptom" → "Diagnosis" → "Action" format
  - Reference scripts/run_paper_5d.ps1, scripts/check_paper_burnin.ps1, etc.

  **Must NOT do**:
  - Do NOT include any actual credentials or tokens
  - Do NOT recommend `rm -rf state/` without explicit user approval steps

  **Recommended Agent Profile**:
  - **Category**: `writing` — operational runbook
  - **Skills**: documentation, python, trading
  - **Why**: Complex doc, needs domain knowledge

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/risk/kill_switch.py` — kill switch behavior
  - `src/monitoring/burnin.py` — reconciliation
  - `scripts/` directory
  - `docs/PAPER_5D_LAUNCH.md` — existing runbook-style content
  - `audit draft 6.1` — runbook requirements

  **Acceptance Criteria**:
  - [ ] `docs/RUNBOOK.md` exists
  - [ ] All 8 listed sections present
  - [ ] Each section uses "Symptom → Diagnosis → Action" format
  - [ ] References real scripts (not fictional)
  - [ ] Total length 300-600 lines

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: RUNBOOK has all required sections
    Tool: Bash (grep)
    Preconditions: docs/RUNBOOK.md exists
    Steps:
      1. foreach ($section in "kill switch fires", "add a new instrument", "rotate Kite", "stuck reconciliation", "angel_symbols", "debug.*paper trade", "runtime_traces", "reconciliation.jsonl") {
           $found = Select-String -Path docs/RUNBOOK.md -Pattern $section
           if (-not $found) { Write-Host "MISSING: $section" }
         }
    Expected Result: No "MISSING:" lines
    Failure Indicators: Missing any required section
    Evidence: .omo/evidence/task-11-runbook-has-all-sections.txt
  ```

  **Commit**: YES
  - Message: `docs(runbook): create RUNBOOK.md with 8 operational procedures`
  - Files: `docs/RUNBOOK.md`

- [ ] 12. Create docs/CONTRIBUTING.md (dev guide)

  **What to do**:
  - Sections: Setup, Dev Workflow, Testing, Code Style, Adding a Strategy, Adding a Broker, Adding an Agent
  - Reference Makefile targets
  - Reference `githooks/pre-commit` install
  - Reference pyproject.toml extras
  - Include a "First PR" checklist

  **Must NOT do**:
  - Do NOT include fictional architecture references
  - Do NOT recommend `git push --force` to main

  **Recommended Agent Profile**:
  - **Category**: `writing` — dev contributing guide
  - **Skills**: documentation, python
  - **Why**: Standard dev doc

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `Makefile:1-40` — dev commands
  - `pyproject.toml:1-81` — project config
  - `.githooks/pre-commit:1-62` — pre-commit setup
  - `src/agents/base.py` — how to add an agent
  - `src/strategies/base.py` — how to add a strategy
  - `src/connectors/` — broker pattern

  **Acceptance Criteria**:
  - [ ] `docs/CONTRIBUTING.md` exists
  - [ ] All 7 listed sections present
  - [ ] Makefile targets referenced
  - [ ] Pre-commit hook install command correct
  - [ ] "How to add a strategy" includes base class import path
  - [ ] "How to add a broker" includes BaseAgent inheritance pattern

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: CONTRIBUTING.md links to actual code
    Tool: Bash (Read + grep)
    Preconditions: docs/CONTRIBUTING.md exists
    Steps:
      1. $baseAgent = Select-String -Path docs/CONTRIBUTING.md -Pattern "src/agents/base.py"
      2. $strategyBase = Select-String -Path docs/CONTRIBUTING.md -Pattern "src/strategies/base.py"
      3. $makeTest = Select-String -Path docs/CONTRIBUTING.md -Pattern "make test"
      4. if (-not $baseAgent -or -not $strategyBase -or -not $makeTest) {
           Write-Host "MISSING LINKS"
         }
    Expected Result: No "MISSING LINKS" output
    Failure Indicators: Missing reference to actual code
    Evidence: .omo/evidence/task-12-contributing-links-code.txt
  ```

  **Commit**: YES
  - Message: `docs(contrib): create CONTRIBUTING.md with dev workflow and patterns`
  - Files: `docs/CONTRIBUTING.md`

- [ ] 13. Create docs/OPERATIONS.md (deploy/monitor/recover)

  **What to do**:
  - Sections: Local Dev, Docker Compose, Railway Deploy, Monitoring Setup, Common Failures, Recovery Procedures, Backup Strategy
  - Reference docker-compose.yml services
  - Reference prometheus.yml targets
  - Document Grafana setup (with secure password)
  - Add a "Disaster Recovery" section: what to do if the database is corrupt

  **Must NOT do**:
  - Do NOT include default passwords
  - Do NOT recommend `rm -rf` without backup steps

  **Recommended Agent Profile**:
  - **Category**: `writing` — operations doc
  - **Skills**: documentation, docker, monitoring
  - **Why**: Standard ops doc

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `docker-compose.yml:1-76` — services
  - `Dockerfile:1-37` — build
  - `railway.json` — Railway deploy
  - `prometheus.yml:1-12` — monitoring
  - `prometheus_alerts.yml:1-29` — alerts
  - `audit draft 6.5` — operations requirements

  **Acceptance Criteria**:
  - [ ] `docs/OPERATIONS.md` exists
  - [ ] All 7 listed sections present
  - [ ] Docker, Railway, monitoring all covered
  - [ ] "Disaster Recovery" section references actual state files
  - [ ] No hardcoded passwords

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: OPERATIONS.md covers all deploy targets
    Tool: Bash (grep)
    Preconditions: docs/OPERATIONS.md exists
    Steps:
      1. foreach ($target in "docker", "railway", "prometheus", "grafana", "postgres", "sqlite") {
           $found = Select-String -Path docs/OPERATIONS.md -Pattern $target -SimpleMatch
           if (-not $found) { Write-Host "MISSING: $target" }
         }
    Expected Result: No "MISSING:" lines
    Failure Indicators: Missing any deploy target
    Evidence: .omo/evidence/task-13-operations-covers-all-targets.txt
  ```

  **Commit**: YES
  - Message: `docs(ops): create OPERATIONS.md with deploy/monitor/recover guide`
  - Files: `docs/OPERATIONS.md`

- [ ] 14. Add coverage threshold to pytest config and CI

  **What to do**:
  - Add `--cov-fail-under=80` to `[tool.pytest.ini_options]` `addopts` in `pyproject.toml`
  - Also add `-ra` (show summary of all result types) and `--strict-markers` and `--strict-config`
  - Verify current coverage using `pytest --cov=src --cov-report=term-missing`
  - If coverage < 80%, add tests for the worst-covered modules first
  - Update CI workflow to use the new addopts
  - Add `--cov-report=xml:coverage.xml` for Codecov integration (if desired)

  **Must NOT do**:
  - Do NOT set the threshold above 85% (current is likely < 50% given the 1377-line execution.py)
  - Do NOT exclude critical modules from coverage

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — needs verification of current coverage
  - **Skills**: python, testing
  - **Why**: Requires running tests + analyzing coverage

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 15-20 (CI work builds on this)
  - **Blocked By**: None

  **References**:
  - `pyproject.toml:79-81` — current pytest config (no addopts)
  - `tests/conftest.py` — existing fixtures
  - `.github/workflows/ci.yml:33-35` — current CI test command

  **Acceptance Criteria**:
  - [ ] `pyproject.toml` has `addopts = ["-ra", "--strict-markers", "--strict-config", "--cov=src", "--cov-fail-under=80"]`
  - [ ] `pytest --cov=src` shows ≥80% line coverage
  - [ ] CI uses the same addopts
  - [ ] No critical modules excluded

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Coverage threshold enforced
    Tool: Bash (pytest)
    Preconditions: Tests pass
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest --cov=src --cov-fail-under=80 2>&1 | Select-String "TOTAL"
    Expected Result: Coverage line shows ≥80% (or test fails with coverage message)
    Failure Indicators: Test passes with coverage < 80%
    Evidence: .omo/evidence/task-14-coverage-threshold-enforced.txt
  ```

  **Commit**: YES
  - Message: `test(coverage): add 80% coverage threshold to pytest config and CI`
  - Files: `pyproject.toml`, `.github/workflows/ci.yml`

- [ ] 15. Add gitleaks to CI workflow for secret scanning

  **What to do**:
  - Read current `.github/workflows/ci.yml`
  - Add a new job `secrets` that runs `gitleaks/gitleaks-action@v2` on push and PR
  - Set `GITLEAKS_LICENSE` from secrets (use GitHub's free tier)
  - Configure to also scan PRs from forks (with caution)
  - Add `gitleaks.toml` config in repo root if needed for false positive tuning
  - Document in `docs/CONTRIBUTING.md`

  **Must NOT do**:
  - Do NOT remove the existing `.githooks/pre-commit` scanner (it's the local backup)
  - Do NOT fail CI on warnings, only on confirmed secrets

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — CI integration
  - **Skills**: github-actions, security
  - **Why**: Standard CI job, well-documented

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `.github/workflows/ci.yml:1-35` — current CI
  - `.githooks/pre-commit:1-62` — existing pre-commit scanner
  - `SECURITY.md:1-87` — past leak details
  - `audit draft 3.1, 6.4` — gitleaks requirement

  **Acceptance Criteria**:
  - [ ] `.github/workflows/ci.yml` has new `secrets` job using gitleaks-action
  - [ ] Job runs on push and pull_request
  - [ ] Job fails on confirmed secrets
  - [ ] `.githooks/pre-commit` still works locally
  - [ ] `docs/CONTRIBUTING.md` mentions CI secret scanning

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: gitleaks catches test secret
    Tool: Bash (gitleaks local)
    Preconditions: gitleaks installed
    Steps:
      1. echo "TRA_KITE_API_KEY=abc123def456ghi789jkl012mno" > /tmp/test_secret.txt
      2. git add /tmp/test_secret.txt
      3. gitleaks detect --source . --no-git
    Expected Result: Leak detected, exit 1
    Failure Indicators: Exit 0 (false negative)
    Evidence: .omo/evidence/task-15-gitleaks-catches-test-secret.txt
  ```

  **Commit**: YES
  - Message: `ci(security): add gitleaks job to detect secrets in PRs`
  - Files: `.github/workflows/ci.yml`, `docs/CONTRIBUTING.md`

- [ ] 16. Add pip-audit to CI workflow for vulnerable dependency detection

  **What to do**:
  - Add a new `audit` job in `.github/workflows/ci.yml` that runs `pip-audit`
  - Install pip-audit in the job: `pip install pip-audit`
  - Run: `pip-audit --strict --requirement pyproject.toml`
  - Set severity threshold to fail only on `HIGH` and `CRITICAL`
  - Cache the pip-audit database for faster runs

  **Must NOT do**:
  - Do NOT fail on `MEDIUM` or `LOW` (too noisy for a paper-trading system)
  - Do NOT use `--strict` flag if it blocks other CI steps

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — CI integration
  - **Skills**: github-actions, security
  - **Why**: Standard CI job

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `.github/workflows/ci.yml:1-35` — current CI
  - `pyproject.toml:6-51` — deps to audit
  - `audit draft 6.4` — pip-audit requirement

  **Acceptance Criteria**:
  - [ ] `.github/workflows/ci.yml` has new `audit` job
  - [ ] Job runs pip-audit with HIGH/CRITICAL severity
  - [ ] Cache key for pip-audit database
  - [ ] Job runs on push and PR

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: pip-audit runs without error
    Tool: Bash (pip-audit)
    Preconditions: pyproject.toml exists
    Steps:
      1. pip install pip-audit
      2. pip-audit -r pyproject.toml 2>&1 | Select-String "No known vulnerabilities"
    Expected Result: Output indicates no known vulnerabilities (or lists only MEDIUM/LOW)
    Failure Indicators: HIGH or CRITICAL vulnerabilities listed
    Evidence: .omo/evidence/task-16-pip-audit-clean.txt
  ```

  **Commit**: YES
  - Message: `ci(deps): add pip-audit job to detect vulnerable dependencies`
  - Files: `.github/workflows/ci.yml`

- [ ] 17. Add ruff format --check to CI workflow

  **What to do**:
  - Update `.github/workflows/ci.yml` to add `ruff format --check src/ tests/` after the existing `ruff check` step
  - Add `ruff format` to `Makefile lint` target
  - Run `ruff format src/ tests/` to format existing code (will modify many files)
  - Verify all tests still pass after formatting

  **Must NOT do**:
  - Do NOT change code style in this task beyond `ruff format` defaults
  - Do NOT skip files (use `ruff format .` to format the whole repo)

  **Recommended Agent Profile**:
  - **Category**: `quick` — formatter application
  - **Skills**: python, ruff
  - **Why**: Mechanical, well-defined

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `.github/workflows/ci.yml:25-27` — current ruff step
  - `Makefile:10-12` — current lint target
  - `pyproject.toml:53-59` — ruff config

  **Acceptance Criteria**:
  - [ ] `ruff format --check src/ tests/` exits 0
  - [ ] CI runs `ruff format --check` as a step
  - [ ] `make lint` includes both `ruff check` and `ruff format --check`
  - [ ] All existing tests pass after format

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: ruff format --check passes on whole repo
    Tool: Bash (ruff)
    Preconditions: Code is formatted
    Steps:
      1. cd "D:\projects\new trade"
      2. ruff format --check src/ tests/ 2>&1
    Expected Result: Exit 0, all files formatted
    Failure Indicators: List of unformatted files
    Evidence: .omo/evidence/task-17-ruff-format-check-pass.txt
  ```

  **Commit**: YES
  - Message: `style: apply ruff format and enforce in CI`
  - Files: many (formatting changes), `.github/workflows/ci.yml`, `Makefile`

- [ ] 18. Add Windows runner to CI workflow (matrix strategy)

  **What to do**:
  - Read current `.github/workflows/ci.yml` (uses `ubuntu-latest`)
  - Convert the `test` job to a matrix with `os: [ubuntu-latest, windows-latest]`
  - Adjust Python setup step for cross-platform (no Linux-specific commands)
  - Adjust coverage upload for cross-platform paths
  - Document in `docs/CONTRIBUTING.md` that CI now tests both

  **Must NOT do**:
  - Do NOT remove the Linux runner (it's faster and catches Linux-specific bugs)
  - Do NOT use macOS (not needed)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — CI matrix
  - **Skills**: github-actions
  - **Why**: Matrix adds complexity

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `.github/workflows/ci.yml:10-35` — current test job
  - `audit draft 6.4, 8.4` — Windows runner requirement

  **Acceptance Criteria**:
  - [ ] CI test job runs on both `ubuntu-latest` and `windows-latest`
  - [ ] Both jobs pass
  - [ ] `docs/CONTRIBUTING.md` mentions cross-platform testing

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: CI matrix runs both OS
    Tool: Bash (gh CLI)
    Preconditions: PR or push to main
    Steps:
      1. gh run list --limit 1 --json matrix | ConvertFrom-Json
    Expected Result: Matrix shows 2 OS entries
    Failure Indicators: Only 1 OS
    Evidence: .omo/evidence/task-18-ci-matrix-2-os.txt
  ```

  **Commit**: YES
  - Message: `ci(matrix): test on both ubuntu-latest and windows-latest`
  - Files: `.github/workflows/ci.yml`, `docs/CONTRIBUTING.md`

- [ ] 19. Add dashboard build step to CI workflow

  **What to do**:
  - Read `dashboard/package.json` to identify build command (`npm run build`)
  - Add a new `dashboard-build` job in `.github/workflows/ci.yml`
  - Use `actions/setup-node@v4` with `node-version: "20"`
  - Run `npm ci && npm run build` in `dashboard/`
  - Verify `dashboard/dist/` is created
  - Optionally upload dist as artifact

  **Must NOT do**:
  - Do NOT commit `dashboard/dist/` (it's gitignored)
  - Do NOT install `dashboard/node_modules/` in main CI (too slow)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — CI integration
  - **Skills**: github-actions, npm
  - **Why**: Standard CI step

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `dashboard/package.json:1-44` — npm scripts
  - `Dockerfile:1-7` — frontend build pattern
  - `audit draft 6.4` — dashboard build requirement

  **Acceptance Criteria**:
  - [ ] CI has new `dashboard-build` job
  - [ ] Job runs on push and PR
  - [ ] Job uses Node 20
  - [ ] `dashboard/dist/` is created on success
  - [ ] Job uploads dist as artifact (optional)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Dashboard builds successfully
    Tool: Bash (npm)
    Preconditions: Node 20 installed
    Steps:
      1. cd dashboard
      2. npm ci
      3. npm run build
    Expected Result: Build succeeds, dashboard/dist/ created
    Failure Indicators: Build error
    Evidence: .omo/evidence/task-19-dashboard-build-success.txt
  ```

  **Commit**: YES
  - Message: `ci(dashboard): add dashboard build step to CI`
  - Files: `.github/workflows/ci.yml`

- [ ] 20. Improve test isolation: use tmp_path for DBs, clean up leaked test DBs

  **What to do**:
  - Identify all hardcoded DB paths in src/ (start with `src/agents/execution.py:27`)
  - Add a `conftest.py` fixture that provides `tmp_path` based DB paths
  - Refactor `ExecutionAgent.__init__` to inject `order_db_path` (it already has this param, verify it's used)
  - Refactor all test files that use the hardcoded path to use the fixture
  - Run all tests, verify they create DBs in tmp_path
  - Delete leaked test DBs from `state/`: `probe_order_state.db`, `test_execution.db`, `test_p01.db`, `test_p02.db`, `test_risk.db`

  **Must NOT do**:
  - Do NOT break the production `_ORDER_DB_PATH` default
  - Do NOT delete the real `order_state.db` or `trading_events.db`

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — refactor + test improvement
  - **Skills**: python, testing
  - **Why**: Touches many files, needs verification

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/agents/execution.py:27` — `_ORDER_DB_PATH = Path("state/order_state.db")`
  - `state/probe_order_state.db`, `test_*.db` — leaked test DBs
  - `tests/conftest.py` — existing fixtures
  - `audit draft 3.8, 2.3` — test isolation requirement

  **Acceptance Criteria**:
  - [ ] `state/` contains no `probe_*.db` or `test_*.db` files after this task
  - [ ] All test files use `tmp_path` fixture for DBs
  - [ ] All existing tests pass
  - [ ] Coverage threshold (from Task 14) still met
  - [ ] New `conftest.py` fixture documented in test docs

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: No test DBs leak to state/
    Tool: Bash (pytest + find)
    Preconditions: Clean state
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ 2>&1 | Select-Object -Last 5
      3. Get-ChildItem state/ -Filter "*.db" | Select-Object Name
    Expected Result: Only order_state.db and trading_events.db present, no test/probe DBs
    Failure Indicators: probe_*.db or test_*.db in state/
    Evidence: .omo/evidence/task-20-no-test-db-leaks.txt
  ```

  **Commit**: YES
  - Message: `test(isolation): use tmp_path for test DBs, remove leaked test DBs from state/`
  - Files: `src/agents/execution.py`, `tests/conftest.py`, many test files, `state/`

- [ ] 21. Persist MetricsCollector to SQLite (no more in-memory wipe on restart)

  **What to do**:
  - Read `src/monitoring/metrics.py` (current: in-memory only)
  - Add a `MetricsStore` class that persists to SQLite (`state/metrics.db`)
  - Schema: `event_counts(timestamp, event_type, count)`, `signal_counts(timestamp, strategy, direction, count)`, etc.
  - Use `INSERT ... ON CONFLICT DO UPDATE` for upserts
  - Add periodic flush (every 10s) via asyncio task
  - On startup, load last 30 days of metrics into in-memory cache
  - `prometheus_text()` reads from cache (still fast)

  **Must NOT do**:
  - Do NOT break the existing `prometheus_text()` interface
  - Do NOT write to a non-SQLite backend (single-machine system)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — refactor with persistence
  - **Skills**: python, sqlite, async
  - **Why**: Architectural change, needs care

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: Tasks 22, 23, 24 (depend on persistent metrics)
  - **Blocked By**: None

  **References**:
  - `src/monitoring/metrics.py:1-122` — current implementation
  - `src/agents/execution.py:32-90` — `_init_order_db` pattern (good reference)
  - `audit draft 5.1` — metrics persistence requirement

  **Acceptance Criteria**:
  - [ ] New `MetricsStore` class in `src/monitoring/metrics_store.py`
  - [ ] `MetricsCollector` writes to `MetricsStore` on every count_*
  - [ ] `state/metrics.db` is created on first count
  - [ ] Restart preserves metrics (verify by restarting, check `prometheus_text()`)
  - [ ] All existing tests pass (may need to mock MetricsStore)
  - [ ] Coverage maintained or improved

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Metrics persist across restarts
    Tool: Bash (pytest + python)
    Preconditions: Clean state
    Steps:
      1. python -c "from src.monitoring.metrics import system_metrics; system_metrics.count_event('TICK'); system_metrics._flush()"
      2. python -c "from src.monitoring.metrics import system_metrics; print(system_metrics.snapshot())"
    Expected Result: Second invocation shows the TICK count from first run
    Failure Indicators: Second invocation shows 0 (no persistence)
    Evidence: .omo/evidence/task-21-metrics-persist-across-restart.txt
  ```

  **Commit**: YES
  - Message: `feat(metrics): persist MetricsCollector to SQLite, no more in-memory wipe`
  - Files: `src/monitoring/metrics.py`, `src/monitoring/metrics_store.py` (new), tests

- [ ] 22. Add daily PnL, exposure, drawdown, open positions metrics

  **What to do**:
  - Extend `MetricsCollector` (or `MetricsStore`) with new counters/gauges:
    - `trading_pnl_daily` (gauge, updated on every fill)
    - `trading_exposure_total` (gauge, sum of position values)
    - `trading_open_positions` (gauge, count)
    - `trading_drawdown_pct` (gauge, current drawdown)
    - `trading_peak_capital` (gauge, all-time peak)
  - Hook into `src/agents/portfolio.py` to update these on position changes
  - Hook into `src/agents/risk_mgmt.py` for drawdown calc
  - Export in `prometheus_text()` with `# HELP` and `# TYPE`
  - Add tests

  **Must NOT do**:
  - Do NOT call these on every event (use a 1-second cache to avoid hot loop)
  - Do NOT include live PnL in paper mode (only paper PnL)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — metrics expansion
  - **Skills**: python, prometheus
  - **Why**: Needs integration with portfolio + risk agents

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: Task 25 (alerts need these)
  - **Blocked By**: Task 21 (needs persistent metrics)

  **References**:
  - `src/monitoring/metrics.py:1-122` — current metrics
  - `src/agents/portfolio.py:1-100` — portfolio state
  - `src/agents/risk_mgmt.py:1-80` — drawdown logic
  - `audit draft 5.2` — missing metrics list

  **Acceptance Criteria**:
  - [ ] `trading_pnl_daily` exported with correct value
  - [ ] `trading_exposure_total` exported with correct value
  - [ ] `trading_open_positions` exported
  - [ ] `trading_drawdown_pct` exported
  - [ ] `trading_peak_capital` exported
  - [ ] Tests cover all 5 new metrics
  - [ ] No metric update takes > 1ms (hot path safe)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: New metrics appear in prometheus output
    Tool: Bash (curl + grep)
    Preconditions: System running with paper trades
    Steps:
      1. curl -s http://localhost:8080/metrics
      2. foreach ($metric in "trading_pnl_daily", "trading_exposure_total", "trading_open_positions", "trading_drawdown_pct", "trading_peak_capital") {
           if (-not (curl -s http://localhost:8080/metrics | Select-String $metric)) {
             Write-Host "MISSING: $metric"
           }
         }
    Expected Result: No "MISSING:" lines
    Failure Indicators: Missing metric
    Evidence: .omo/evidence/task-22-new-metrics-exported.txt
  ```

  **Commit**: YES
  - Message: `feat(metrics): add daily PnL, exposure, drawdown, open positions metrics`
  - Files: `src/monitoring/metrics.py`, `src/agents/portfolio.py`, `src/agents/risk_mgmt.py`, tests

- [ ] 23. Add per-strategy attribution metrics (trading_attribution_pnl_total)

  **What to do**:
  - Read `src/monitoring/attribution.py` (already has attribution logic)
  - Extend `MetricsCollector` with per-strategy PnL counter:
    - `trading_attribution_pnl_total{strategy="..."}` (counter, accumulates realized PnL)
  - Hook into `src/agents/portfolio.py` or attribution to update on each fill attribution
  - Export in `prometheus_text()` with strategy label
  - Add tests covering 3+ strategies

  **Must NOT do**:
  - Do NOT use unbounded cardinality (only the 3 active strategies + filter strategies)
  - Do NOT include unrealized PnL (only realized)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — metrics with labels
  - **Skills**: python, prometheus
  - **Why**: Standard metric pattern

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: Task 21

  **References**:
  - `src/monitoring/attribution.py:1-200` — existing attribution
  - `docs/active_strategy_set.md` — list of 3 active + 2 filter strategies
  - `audit draft 5.2` — missing attribution metric

  **Acceptance Criteria**:
  - [ ] `trading_attribution_pnl_total{strategy="momentum"}` exported
  - [ ] At least 5 strategy labels exported (momentum, sideways_reversion, vwap_reversion, ema200, adx)
  - [ ] Value updates on each fill
  - [ ] Tests cover all 5 strategy labels
  - [ ] No label cardinality explosion (limited to known strategies)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Per-strategy attribution exported
    Tool: Bash (curl + grep)
    Preconditions: Paper trades running with multiple strategies
    Steps:
      1. curl -s http://localhost:8080/metrics | Select-String "trading_attribution_pnl_total"
    Expected Result: Multiple strategy labels present
    Failure Indicators: Single label or no labels
    Evidence: .omo/evidence/task-23-attribution-per-strategy.txt
  ```

  **Commit**: YES
  - Message: `feat(metrics): add per-strategy PnL attribution metrics`
  - Files: `src/monitoring/metrics.py`, `src/monitoring/attribution.py`, tests

- [ ] 24. Add slippage, fill rate, broker API error metrics

  **What to do**:
  - Extend `MetricsCollector` with:
    - `trading_slippage_bps` (histogram, per fill)
    - `trading_fill_rate` (gauge, % over last 100 orders)
    - `trading_broker_api_errors_total{endpoint="..."}` (counter)
    - `trading_reconciliation_status` (gauge, 0=ok, 1=mismatch)
  - Hook into `src/agents/execution.py` for slippage on each fill
  - Hook into broker connector base for API errors
  - Hook into `src/monitoring/burnin.py` for reconciliation status
  - Add tests

  **Must NOT do**:
  - Do NOT use high-cardinality labels for API errors (e.g., not per-symbol, per-endpoint only)
  - Do NOT include real broker secrets in label values

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — metrics expansion
  - **Skills**: python, prometheus
  - **Why**: Standard metrics

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: Task 21

  **References**:
  - `src/agents/execution.py:1-100` — fill flow
  - `src/connectors/angel/client.py` — broker error pattern
  - `src/monitoring/burnin.py` — reconciliation
  - `audit draft 5.2` — missing metrics list

  **Acceptance Criteria**:
  - [ ] `trading_slippage_bps` exported as histogram
  - [ ] `trading_fill_rate` exported as gauge
  - [ ] `trading_broker_api_errors_total{endpoint="..."}` exported
  - [ ] `trading_reconciliation_status` exported (0 or 1)
  - [ ] Tests cover all 4 new metrics
  - [ ] No metric causes hot-path slowdown > 1ms

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: All execution metrics present
    Tool: Bash (curl + grep)
    Preconditions: System running
    Steps:
      1. curl -s http://localhost:8080/metrics
      2. foreach ($metric in "trading_slippage_bps", "trading_fill_rate", "trading_broker_api_errors_total", "trading_reconciliation_status") {
           if (-not (curl -s http://localhost:8080/metrics | Select-String $metric)) {
             Write-Host "MISSING: $metric"
           }
         }
    Expected Result: No "MISSING:" lines
    Failure Indicators: Missing metric
    Evidence: .omo/evidence/task-24-execution-metrics-exported.txt
  ```

  **Commit**: YES
  - Message: `feat(metrics): add slippage, fill rate, broker API errors, reconciliation metrics`
  - Files: `src/monitoring/metrics.py`, `src/agents/execution.py`, `src/connectors/`, tests

- [ ] 25. Expand prometheus_alerts.yml from 3 to 10+ alerts

  **What to do**:
  - Read current `prometheus_alerts.yml` (3 alerts)
  - Add 7+ new alerts:
    - `DailyPnLApproaching` (warning at 80% of daily loss limit)
    - `ReconciliationMismatch` (drift detected, critical)
    - `StrategyDecay` (rolling Sharpe < 0 for 5 days, warning)
    - `HighLatency` (p95 latency > 500ms, warning)
    - `NoMarketData` (no ticks in 5 min during market hours, critical)
    - `OrderStuck` (order pending > 60s, warning)
    - `FillRateLow` (fill rate < 80% over 1h, warning)
    - `BacklogGrowth` (event queue depth growing, warning)
  - Each alert needs: `expr`, `for`, `labels.severity`, `annotations.summary`, `annotations.description`
  - Test that prometheus accepts the file (`promtool check config`)

  **Must NOT do**:
  - Do NOT remove existing 3 alerts
  - Do NOT use PromQL that requires specific metric names that don't exist yet (coordinate with Tasks 21-24)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — alert config
  - **Skills**: prometheus, yaml
  - **Why**: Standard alert config

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: Tasks 21-24 (need metrics for alerts to work)

  **References**:
  - `prometheus_alerts.yml:1-29` — current 3 alerts
  - `prometheus.yml:1-12` — alert loading
  - `audit draft 5.3` — missing alerts list

  **Acceptance Criteria**:
  - [ ] `prometheus_alerts.yml` has 10+ alert rules
  - [ ] `promtool check config prometheus.yml` passes
  - [ ] Each new alert has expr, for, labels, annotations
  - [ ] All 7 new alerts reference metrics that exist after Task 21-24

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: promtool accepts the config
    Tool: Bash (promtool)
    Preconditions: promtool installed
    Steps:
      1. promtool check config prometheus.yml
      2. promtool check rules prometheus_alerts.yml
    Expected Result: Both exit 0
    Failure Indicators: Parse error or rule syntax error
    Evidence: .omo/evidence/task-25-promtool-config-valid.txt
  ```

  **Commit**: YES
  - Message: `feat(alerts): expand prometheus_alerts.yml from 3 to 10+ alerts`
  - Files: `prometheus_alerts.yml`

- [ ] 26. Add state file retention policy (auto-cleanup >30 days events)

  **What to do**:
  - Read `src/monitoring/burnin.py` for reconciliation loop pattern
  - Add a new `state_cleanup.py` module with:
    - `cleanup_old_events(db_path, days=30)` — deletes events older than N days from `trading_events.db`
    - `cleanup_angel_symbols(cache_path, max_age_days=7)` — refreshes symbol cache
    - `cleanup_old_logs(log_dir, days=30)` — rotates `runtime_traces/`
  - Hook into `main.py` to run cleanup daily at midnight
  - Add retention config to `settings.py`: `state_retention_days: int = 30`
  - Add tests

  **Must NOT do**:
  - Do NOT delete the current day
  - Do NOT run cleanup without a backup

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — operational retention
  - **Skills**: python, sqlite
  - **Why**: Touches live data, needs care

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `state/trading_events.db` (35MB) — needs cleanup
  - `state/angel_symbols.json` (26.6MB) — needs TTL
  - `logs/runtime_traces/` — needs rotation
  - `src/monitoring/burnin.py` — loop pattern
  - `audit draft 9.1` — retention requirement

  **Acceptance Criteria**:
  - [ ] `src/monitoring/state_cleanup.py` exists
  - [ ] `cleanup_old_events` deletes events older than `state_retention_days`
  - [ ] `cleanup_angel_symbols` refreshes if older than 7 days
  - [ ] `cleanup_old_logs` rotates `runtime_traces/`
  - [ ] `main.py` runs cleanup daily at midnight
  - [ ] Tests cover all 3 cleanup functions
  - [ ] Cleanup completes in < 5s for 35MB DB

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Old events deleted
    Tool: Bash (python + sqlite3)
    Preconditions: Test DB with old events
    Steps:
      1. python -c "
         import sqlite3, datetime
         from src.monitoring.state_cleanup import cleanup_old_events
         conn = sqlite3.connect('test.db')
         # Insert old event
         conn.execute('CREATE TABLE events (timestamp TEXT, data TEXT)')
         old_date = (datetime.datetime.now() - datetime.timedelta(days=60)).isoformat()
         conn.execute('INSERT INTO events VALUES (?, ?)', (old_date, 'old'))
         new_date = datetime.datetime.now().isoformat()
         conn.execute('INSERT INTO events VALUES (?, ?)', (new_date, 'new'))
         conn.commit()
         conn.close()
         cleanup_old_events(Path('test.db'), days=30)
         conn = sqlite3.connect('test.db')
         rows = conn.execute('SELECT data FROM events').fetchall()
         assert rows == [('new',)], f'Expected [new], got {rows}'
         print('PASS')
       "
    Expected Result: "PASS" printed
    Failure Indicators: AssertionError or ImportError
    Evidence: .omo/evidence/task-26-old-events-deleted.txt
  ```

  **Commit**: YES
  - Message: `feat(retention): add state file retention policy, daily cleanup loop`
  - Files: `src/monitoring/state_cleanup.py` (new), `src/config/settings.py`, `src/main.py`, tests

- [ ] 27. Wire dashboard /api/output/validation_report to real data (not placeholders)

  **What to do**:
  - Read `dashboard/server.py:406-451` (current: all None values)
  - Replace placeholder returns with calls to `src/monitoring/attribution.py` and `src/agents/portfolio.py`
  - Add fields: `total_return`, `annual_return`, `max_drawdown`, `sharpe_ratio`, `volatility`, `total_trades`, `final_value`, `initial_capital`, `benchmark_return`, `alpha`
  - Also fix `experiment_report` (line 470-478) to use real reflection data
  - Add tests with mock attribution data

  **Must NOT do**:
  - Do NOT return fake/hardcoded numbers (must be real)
  - Do NOT break the existing `/api/paper-report` endpoint

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — dashboard wiring
  - **Skills**: python, fastapi
  - **Why**: Standard API wiring

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: Task 21 (needs persistent metrics for 30-day stats)

  **References**:
  - `dashboard/server.py:406-451` — placeholder validation_report
  - `dashboard/server.py:470-478` — placeholder experiment_report
  - `src/monitoring/attribution.py:1-200` — real attribution
  - `src/agents/portfolio.py:1-100` — real portfolio
  - `audit draft 4.8` — placeholder report issue

  **Acceptance Criteria**:
  - [ ] `/api/output/validation_report` returns real values (not None)
  - [ ] `/api/output/experiment_report` returns real data (not zeros)
  - [ ] `sharpe_ratio` and `max_drawdown` match attribution calculations
  - [ ] Tests cover the endpoint with mock data
  - [ ] All previous dashboard tests pass

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Validation report returns real data
    Tool: Bash (pytest + curl)
    Preconditions: System running with paper trades
    Steps:
      1. curl -s http://localhost:8081/api/output/validation_report
      2. curl -s http://localhost:8081/api/output/validation_report | python -c "import json, sys; d = json.load(sys.stdin); assert d['summary']['total_return'] is not None, 'total_return is None'"
    Expected Result: No AssertionError
    Failure Indicators: "total_return is None" or empty dict
    Evidence: .omo/evidence/task-27-validation-report-real-data.txt
  ```

  **Commit**: YES
  - Message: `feat(dashboard): wire validation_report and experiment_report to real data`
  - Files: `dashboard/server.py`, `src/monitoring/attribution.py`, tests

- [ ] 28. Enable mypy strict mode (remove 12 disable_error_code)

  **What to do**:
  - Read `pyproject.toml:61-77` (current mypy config with 12+ disabled codes)
  - Remove the `disable_error_code = [...]` line entirely
  - Run `mypy src/` and fix all reported errors
  - For each module, fix types properly (add type hints, use cast, use Protocol)
  - For unfixable errors (3rd party libs without stubs), add `# type: ignore[import]` to that line
  - Set `strict = true` in mypy config
  - Update CI to fail on mypy errors

  **Must NOT do**:
  - Do NOT re-add `disable_error_code` for the same codes
  - Do NOT use `Any` everywhere to silence mypy

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — type fixes across many files
  - **Skills**: python, mypy
  - **Why**: Touches many files, needs iteration

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `pyproject.toml:61-77` — current mypy config
  - `src/` directory — files to type-check
  - `audit draft 3.6` — mypy disabled issue

  **Acceptance Criteria**:
  - [ ] `pyproject.toml` has no `disable_error_code`
  - [ ] `pyproject.toml` has `strict = true`
  - [ ] `mypy src/` exits 0
  - [ ] CI fails on mypy errors
  - [ ] No `# type: ignore` without specific code (e.g., `# type: ignore[import-untyped]`)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: mypy strict passes
    Tool: Bash (mypy)
    Preconditions: pyproject.toml updated
    Steps:
      1. cd "D:\projects\new trade"
      2. mypy src/ 2>&1 | Select-String "Success: no issues found"
    Expected Result: "Success: no issues found" in output
    Failure Indicators: Any error or "Found N errors"
    Evidence: .omo/evidence/task-28-mypy-strict-pass.txt
  ```

  **Commit**: YES
  - Message: `chore(types): enable mypy strict mode, fix all type errors`
  - Files: `pyproject.toml`, many `src/` files (type fixes)

- [ ] 29. Add ruff B, C4, SIM, PT, TID rule sets

  **What to do**:
  - Read `pyproject.toml:57-59` (current ruff config: only E, F, I, N, W, UP)
  - Add `B` (bugbear), `C4` (comprehensions), `SIM` (simplify), `PT` (pytest), `TID` (tidy imports)
  - Run `ruff check --fix src/ tests/` to auto-fix what's possible
  - For remaining issues, fix manually or add `noqa: RULE` with justification
  - Update CI to fail on these rules

  **Must NOT do**:
  - Do NOT add `S` (security) — too many false positives for trading code (e.g., subprocess use is intentional in monitor.py)
  - Do NOT add `ANN` (annotations) — would require adding type hints everywhere (separate task)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — linter config + fixes
  - **Skills**: python, ruff
  - **Why**: Many small fixes across files

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `pyproject.toml:57-59` — current ruff config
  - `src/` — files to lint
  - `audit draft 3.7` — ruff config gaps

  **Acceptance Criteria**:
  - [ ] `pyproject.toml` selects B, C4, SIM, PT, TID in addition to existing
  - [ ] `ruff check src/ tests/` exits 0
  - [ ] CI uses the new rules
  - [ ] No rule disabled without justification comment

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: ruff with new rules passes
    Tool: Bash (ruff)
    Preconditions: pyproject.toml updated
    Steps:
      1. cd "D:\projects\new trade"
      2. ruff check src/ tests/ 2>&1 | Select-String "All checks passed"
    Expected Result: "All checks passed" in output
    Failure Indicators: Any rule violation
    Evidence: .omo/evidence/task-29-ruff-new-rules-pass.txt
  ```

  **Commit**: YES
  - Message: `chore(lint): add ruff B, C4, SIM, PT, TID rule sets, auto-fix where possible`
  - Files: `pyproject.toml`, many `src/` files (lint fixes)

- [ ] 30. Fix kill_switch __new__ singleton antipattern (lazy lock init)

  **What to do**:
  - Read `src/risk/kill_switch.py:8-22` (current `__new__` pattern)
  - Refactor to: instance created in `__init__`, lazy lock creation in `check_limits`/`trigger` via a method
  - OR: keep singleton but use a class method `get_instance()` and lazy init
  - Add a `setup()` method that's idempotent (no-op if already set up)
  - Wrap `trigger()` in the lock (currently only `check_limits` is)
  - Add tests for concurrent `check_limits` and `trigger` calls

  **Must NOT do**:
  - Do NOT break the existing `KillSwitch().active` / `KillSwitch().reason` API
  - Do NOT remove the singleton pattern (used in many places)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — refactor with concurrency
  - **Skills**: python, asyncio
  - **Why**: Concurrency bugs are subtle

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/risk/kill_switch.py:8-22` — current antipattern
  - `src/risk/kill_switch.py:86-115` — `trigger` not in lock
  - `tests/test_risk_mgmt_phase2.py` — existing tests
  - `audit draft 4.2` — kill switch issues

  **Acceptance Criteria**:
  - [ ] `asyncio.Lock()` is created lazily (not in `__new__`)
  - [ ] `trigger()` is wrapped in the lock
  - [ ] `setup()` is idempotent
  - [ ] All existing kill switch tests pass
  - [ ] New test: concurrent check_limits + trigger doesn't double-trigger
  - [ ] `KillSwitch().active` still works

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Concurrent trigger doesn't double-fire
    Tool: Bash (pytest)
    Preconditions: Tests pass currently
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/test_risk_mgmt_phase2.py -v -k "kill" 2>&1 | Select-String "PASSED"
    Expected Result: All kill switch tests pass
    Failure Indicators: Any test failure
    Evidence: .omo/evidence/task-30-kill-switch-tests-pass.txt
  ```

  **Commit**: YES
  - Message: `refactor(killswitch): lazy lock init, wrap trigger in lock, idempotent setup`
  - Files: `src/risk/kill_switch.py`, tests

- [ ] 31. Fix execution.py system.py direct attribute access (force_paper_mode method)

  **What to do**:
  - Read `src/system.py:136-161` (current: `self.execution._paper_trading = True`)
  - Add a public method `force_paper_mode()` on `ExecutionAgent`:
    ```python
    def force_paper_mode(self) -> None:
        """Force execution to paper mode, clearing any broker reference."""
        self._paper_trading = True
        self._broker = None
    ```
  - Update `system.py:141-143, 159-161` to call this method instead of direct attribute access
  - Also: do the same for any other direct attribute access in system.py
  - Add test for `force_paper_mode()`

  **Must NOT do**:
  - Do NOT remove the underlying `_paper_trading` attribute (used internally)
  - Do NOT change the public API of ExecutionAgent

  **Recommended Agent Profile**:
  - **Category**: `quick` — small refactor
  - **Skills**: python, refactoring
  - **Why**: Bounded, well-defined

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/system.py:141-143` — `self.execution._paper_trading = True`
  - `src/system.py:159-161` — same pattern on connection failure
  - `src/agents/execution.py:94-100` — ExecutionAgent init
  - `audit draft 4.3` — direct attribute access issue

  **Acceptance Criteria**:
  - [ ] `ExecutionAgent.force_paper_mode()` exists
  - [ ] `system.py` calls `force_paper_mode()` instead of direct attribute access
  - [ ] No `self.execution._paper_trading =` or `self.execution._broker =` outside ExecutionAgent
  - [ ] All existing tests pass
  - [ ] New test for `force_paper_mode()`

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: No direct _paper_trading assignment outside ExecutionAgent
    Tool: Bash (grep)
    Preconditions: Code in expected state
    Steps:
      1. $results = Select-String -Path src/**/*.py -Pattern "_paper_trading\s*=" -Recurse
      2. foreach ($r in $results) {
           if ($r.Path -notlike "*/agents/execution.py") {
             Write-Host "DIRECT ACCESS: $($r.Path):$($r.LineNumber)"
           }
         }
    Expected Result: No "DIRECT ACCESS:" lines (only inside execution.py)
    Failure Indicators: Direct access from other files
    Evidence: .omo/evidence/task-31-no-direct-attr-access.txt
  ```

  **Commit**: YES
  - Message: `refactor(execution): add force_paper_mode method, remove direct attribute access from system.py`
  - Files: `src/agents/execution.py`, `src/system.py`, tests

- [ ] 32. Fix execution.py _ORDER_DB_PATH to be configurable per env

  **What to do**:
  - Read `src/agents/execution.py:27` (`_ORDER_DB_PATH = Path("state/order_state.db")`)
  - Make it a module-level constant but allow override via env var: `os.environ.get("TRA_ORDER_DB_PATH", "state/order_state.db")`
  - Verify `ExecutionAgent.__init__` uses this (it accepts `order_db_path` param)
  - Add to `.env.example`: `TRA_ORDER_DB_PATH=state/order_state.db`
  - Add to `docs/OPERATIONS.md`: how to use a different DB for staging
  - Add test that env var override works

  **Must NOT do**:
  - Do NOT break the default path (most users won't set the env var)
  - Do NOT use a global mutable variable (just module-level constant)

  **Recommended Agent Profile**:
  - **Category**: `quick` — small env config change
  - **Skills**: python, config
  - **Why**: Trivial

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/agents/execution.py:27` — `_ORDER_DB_PATH`
  - `src/agents/execution.py:94` — `__init__` already accepts param
  - `.env.example` — env var pattern
  - `audit draft 4.1` — DB path hardcoded

  **Acceptance Criteria**:
  - [ ] `_ORDER_DB_PATH` reads from `TRA_ORDER_DB_PATH` env var
  - [ ] Default is still `state/order_state.db`
  - [ ] `.env.example` has `TRA_ORDER_DB_PATH` documented
  - [ ] Test verifies env var override works
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Env var override works
    Tool: Bash (pytest)
    Preconditions: env var set
    Steps:
      1. $env:TRA_ORDER_DB_PATH = "/tmp/test_order.db"
      2. python -c "from src.agents.execution import _ORDER_DB_PATH; print(_ORDER_DB_PATH)"
    Expected Result: Path object pointing to /tmp/test_order.db
    Failure Indicators: Default path (state/order_state.db)
    Evidence: .omo/evidence/task-32-order-db-path-env-override.txt
  ```

  **Commit**: YES
  - Message: `feat(config): make _ORDER_DB_PATH overridable via TRA_ORDER_DB_PATH env var`
  - Files: `src/agents/execution.py`, `.env.example`, `docs/OPERATIONS.md`, tests

- [ ] 33. Fix settings.py eager secret loading (add reload() method)

  **What to do**:
  - Read `src/config/settings.py:96-131` (current: eager load in `model_validator`)
  - Refactor to: lazy load (only on first access of a `_*_secret` attribute)
  - Add a `reload()` method that re-reads from Vault/env
  - Add a `SIGHUP` handler in `main.py` that calls `settings.reload()` on signal
  - Add tests

  **Must NOT do**:
  - Do NOT change the public API of `settings` (it's a singleton)
  - Do NOT remove the existing env-var-only fallback (only add Vault as enhancement)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — refactor for hot-reload
  - **Skills**: python, pydantic
  - **Why**: Touches global state

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/config/settings.py:96-131` — eager validator
  - `src/main.py:191-203` — signal handler
  - `src/utils/vault.py:66-90` — `load_secure_secret`
  - `audit draft 4.5` — settings eager loading

  **Acceptance Criteria**:
  - [ ] `settings.reload()` method exists
  - [ ] SIGHUP signal triggers reload in main.py
  - [ ] Lazy load: secrets are only fetched on first attribute access
  - [ ] All existing tests pass
  - [ ] New test: `reload()` re-reads from updated env

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: SIGHUP triggers reload
    Tool: Bash (python)
    Preconditions: System running
    Steps:
      1. $env:TRA_KITE_API_KEY = "first_key"
      2. python -c "from src.config.settings import settings; print(settings.kite_api_key)"
      3. $env:TRA_KITE_API_KEY = "second_key"
      4. python -c "import signal, os, sys; os.kill(os.getpid(), signal.SIGHUP); from src.config.settings import settings; print(settings.kite_api_key)"
    Expected Result: "second_key" (or reload log line)
    Failure Indicators: "first_key" (stale)
    Evidence: .omo/evidence/task-33-sighup-reload.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add settings.reload() for hot-reload via SIGHUP, lazy secret loading`
  - Files: `src/config/settings.py`, `src/main.py`, tests

- [ ] 34. Add watchlist validation (dedup, format, min/max count)

  **What to do**:
  - Read `src/system.py:167-169` (current `set_watchlist`)
  - Add a `validate_watchlist(instruments: list[str]) -> list[str]` function in `src/utils/`:
    - Dedup (preserves order)
    - Strip whitespace
    - Uppercase
    - Remove empty strings
    - Validate format (alphanumeric + hyphen, length 1-20)
    - Validate count (1-50, configurable)
  - Update `set_watchlist` to call validate first
  - Log a warning if validation changes the list
  - Add tests covering all validation cases

  **Must NOT do**:
  - Do NOT add broker-specific symbol validation (e.g., "RELIANCE-EQ" vs "RELIANCE") — that's broker-specific
  - Do NOT break the existing watchlist env var format

  **Recommended Agent Profile**:
  - **Category**: `quick` — small validation function
  - **Skills**: python
  - **Why**: Bounded

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/system.py:167-169` — current set_watchlist
  - `src/utils/timeframe.py` — example utility module
  - `audit draft 4.4` — watchlist validation

  **Acceptance Criteria**:
  - [ ] `validate_watchlist` function in `src/utils/`
  - [ ] Dedups, strips, uppercases, validates format
  - [ ] Enforces 1-50 instrument count
  - [ ] `set_watchlist` uses it
  - [ ] Tests cover all validation cases
  - [ ] All existing tests pass

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Watchlist dedup and uppercase
    Tool: Bash (pytest)
    Preconditions: Function exists
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "watchlist" -v 2>&1 | Select-String "PASSED"
    Expected Result: All watchlist tests pass
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-34-watchlist-validation-tests.txt
  ```

  **Commit**: YES
  - Message: `feat(utils): add validate_watchlist, dedup/format/count validation`
  - Files: `src/utils/watchlist.py` (new), `src/system.py`, tests

- [ ] 35. Extract OrderRepository class from execution.py (DB CRUD)

  **What to do**:
  - Read `src/agents/execution.py:32-90` (DB init) and the methods that write to DB
  - Create new `src/agents/execution/order_repository.py`:
    - Class `OrderRepository` with methods: `init()`, `persist_order()`, `update_order_status()`, `persist_fill()`, `get_order()`, `get_fills_for_order()`, `list_open_orders()`
    - All DB-related code moves here
    - Use connection pooling (aiosqlite pool or single connection with lock)
  - Refactor `execution.py` to use `OrderRepository` instead of inline DB code
  - Add tests for `OrderRepository` with `tmp_path` fixture (per Task 20)
  - Verify all 329 existing tests pass

  **Must NOT do**:
  - Do NOT change the SQL schema
  - Do NOT break the asyncio.Lock pattern from BUG-3 (the lock is critical)
  - Do NOT use `check_same_thread=False` without the lock

  **Recommended Agent Profile**:
  - **Category**: `deep` — refactor of critical module
  - **Skills**: python, sqlite, async, refactoring
  - **Why**: Touches the most critical file in the system

  **Parallelization**:
  - **Can Run In Parallel**: YES (different sub-module)
  - **Parallel Group**: Wave 6
  - **Blocks**: Tasks 36-39 (other extractions depend on this)
  - **Blocked By**: None (can extract in any order)

  **References**:
  - `src/agents/execution.py:32-90` — `_init_order_db`
  - `src/agents/execution.py` — search for `aiosqlite.connect` and DB methods
  - `audit draft 2.2` — god-module issue

  **Acceptance Criteria**:
  - [ ] `src/agents/execution/order_repository.py` exists
  - [ ] `OrderRepository` class has all DB methods
  - [ ] `execution.py` no longer has inline DB code
  - [ ] All existing tests pass (329 → 329, no regressions)
  - [ ] New `OrderRepository` tests with `tmp_path`
  - [ ] Coverage maintained (80%+)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: OrderRepository CRUD works
    Tool: Bash (pytest)
    Preconditions: Module extracted
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "order_repository" -v 2>&1 | Select-String "PASSED"
    Expected Result: All repository tests pass
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-35-order-repository-tests.txt

  Scenario: All existing tests still pass
    Tool: Bash (pytest)
    Preconditions: Refactor complete
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ 2>&1 | Select-String "passed"
    Expected Result: ≥329 passed
    Failure Indicators: Fewer than 329 passed
    Evidence: .omo/evidence/task-35-no-regressions.txt
  ```

  **Commit**: YES
  - Message: `refactor(execution): extract OrderRepository class, separate DB concerns`
  - Files: `src/agents/execution.py`, `src/agents/execution/order_repository.py` (new), tests

- [ ] 36. Extract PaperFillSimulator class from execution.py

  **What to do**:
  - Read `src/agents/execution.py` and identify paper fill logic (look for `_paper_trading`, `simulated`, fill simulation)
  - Create new `src/agents/execution/paper_fill.py`:
    - Class `PaperFillSimulator` with methods: `simulate_fill(order, market_price) -> FillEvent`, `apply_slippage(price) -> price`, `apply_costs(price, quantity) -> total_cost`
  - Move all paper-mode fill logic here
  - Refactor `execution.py` to use it
  - Add tests covering slippage, partial fills, no-liquidity scenarios

  **Must NOT do**:
  - Do NOT change the slippage model (still 5bps flat, per plan.md T3)
  - Do NOT break the paper fill assumptions

  **Recommended Agent Profile**:
  - **Category**: `deep` — refactor of fill logic
  - **Skills**: python, async, testing
  - **Why**: Trading logic, needs care

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6
  - **Blocks**: None
  - **Blocked By**: Task 35 (need OrderRepository first)

  **References**:
  - `src/agents/execution.py` — search for `paper_trading` and `FillEvent`
  - `tests/test_execution_paper_fill.py` — existing paper fill tests
  - `audit draft 2.2` — god-module

  **Acceptance Criteria**:
  - [ ] `src/agents/execution/paper_fill.py` exists
  - [ ] `PaperFillSimulator` class with all fill logic
  - [ ] `execution.py` no longer has inline fill simulation
  - [ ] All existing tests pass
  - [ ] New tests for simulator

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: PaperFillSimulator tests pass
    Tool: Bash (pytest)
    Preconditions: Module extracted
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "paper_fill" -v 2>&1 | Select-String "PASSED"
    Expected Result: All paper fill tests pass
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-36-paper-fill-tests.txt
  ```

  **Commit**: YES
  - Message: `refactor(execution): extract PaperFillSimulator class`
  - Files: `src/agents/execution.py`, `src/agents/execution/paper_fill.py` (new), tests

- [ ] 37. Extract TwapIcebergEngine class from execution.py

  **What to do**:
  - Read `src/agents/execution.py` and identify TWAP/iceberg logic (look for `_twap_orders`, `iceberg`, `twap_state`)
  - Create new `src/agents/execution/twap_iceberg.py`:
    - Class `TwapIcebergEngine` with methods: `start_twap(order, duration_seconds, slices)`, `start_iceberg(order, visible_quantity)`, `tick()` (called periodically), `cancel(twap_id)`
    - State management for active TWAP/iceberg orders
  - Move all TWAP/iceberg logic here
  - Refactor `execution.py` to use it
  - Add tests covering normal execution, partial fills, cancellation

  **Must NOT do**:
  - Do NOT change the TWAP interval default (30s, per plan.md)
  - Do NOT break existing TWAP/iceberg tests

  **Recommended Agent Profile**:
  - **Category**: `deep` — refactor of execution algorithms
  - **Skills**: python, async
  - **Why**: Complex async state machine

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6
  - **Blocks**: None
  - **Blocked By**: Task 35

  **References**:
  - `src/agents/execution.py` — search for `twap`, `iceberg`
  - `tests/test_execution_twap.py` — existing TWAP tests
  - `tests/test_iceberg_execution.py` — existing iceberg tests
  - `audit draft 2.2` — god-module

  **Acceptance Criteria**:
  - [ ] `src/agents/execution/twap_iceberg.py` exists
  - [ ] `TwapIcebergEngine` class with all algorithms
  - [ ] `execution.py` no longer has inline TWAP/iceberg logic
  - [ ] All existing TWAP/iceberg tests pass
  - [ ] New tests for the engine

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: TwapIcebergEngine tests pass
    Tool: Bash (pytest)
    Preconditions: Module extracted
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/test_execution_twap.py tests/test_iceberg_execution.py -v 2>&1 | Select-String "PASSED"
    Expected Result: All TWAP/iceberg tests pass
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-37-twap-iceberg-tests.txt
  ```

  **Commit**: YES
  - Message: `refactor(execution): extract TwapIcebergEngine class`
  - Files: `src/agents/execution.py`, `src/agents/execution/twap_iceberg.py` (new), tests

- [ ] 38. Extract SignalQueue class from execution.py

  **What to do**:
  - Read `src/agents/execution.py` and identify signal queue logic (look for `_pending_signals`, `_pending_orders`, `pending_signal`)
  - Create new `src/agents/execution/signal_queue.py`:
    - Class `SignalQueue` with methods: `enqueue(signal)`, `dequeue() -> Optional[signal]`, `peek()`, `size()`, `clear()`, `has_signal(signal_event_id) -> bool`
  - Move all queue management here
  - Refactor `execution.py` to use it
  - Add tests covering FIFO order, deduplication (the BUG-2 fix), concurrent enqueue

  **Must NOT do**:
  - Do NOT change the signal-to-order correlation logic (per BUG-2: signal_event_id is mandatory)
  - Do NOT break the asyncio.Lock for queue access

  **Recommended Agent Profile**:
  - **Category**: `deep` — refactor of queue logic
  - **Skills**: python, async, queues
  - **Why**: Concurrency-sensitive

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6
  - **Blocks**: None
  - **Blocked By**: Task 35

  **References**:
  - `src/agents/execution.py` — search for `_pending_signals`, `_pending_orders`
  - `audit draft 2.2` — god-module
  - BUG-2 from `plan.md` — signal_event_id mandatory

  **Acceptance Criteria**:
  - [ ] `src/agents/execution/signal_queue.py` exists
  - [ ] `SignalQueue` class with all queue methods
  - [ ] `execution.py` no longer has inline queue logic
  - [ ] All existing tests pass
  - [ ] New tests for queue (FIFO, dedup, concurrency)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: SignalQueue tests pass
    Tool: Bash (pytest)
    Preconditions: Module extracted
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "signal_queue" -v 2>&1 | Select-String "PASSED"
    Expected Result: All queue tests pass
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-38-signal-queue-tests.txt
  ```

  **Commit**: YES
  - Message: `refactor(execution): extract SignalQueue class`
  - Files: `src/agents/execution.py`, `src/agents/execution/signal_queue.py` (new), tests

- [ ] 39. Extract ExecutionCore (orchestrator) from execution.py

  **What to do**:
  - After Tasks 35-38, `execution.py` should be a thin orchestrator
  - Create new `src/agents/execution/execution_core.py`:
    - Class `ExecutionCore` that composes `OrderRepository`, `PaperFillSimulator`, `TwapIcebergEngine`, `SignalQueue`
    - Methods: `on_signal()`, `on_fill()`, `on_order_status()`, `place_order()`, `cancel_order()`
  - Refactor `ExecutionAgent` to be a thin wrapper around `ExecutionCore`
  - The `BaseAgent` interface stays on `ExecutionAgent`
  - Add tests

  **Must NOT do**:
  - Do NOT break the `BaseAgent` interface (on_start, on_event, etc.)
  - Do NOT change the public API of `ExecutionAgent`

  **Recommended Agent Profile**:
  - **Category**: `deep` — orchestrator refactor
  - **Skills**: python, design-patterns
  - **Why**: Architectural refactor

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6
  - **Blocks**: Task 40 (caller updates)
  - **Blocked By**: Tasks 35, 36, 37, 38

  **References**:
  - `src/agents/base.py` — BaseAgent interface
  - `src/agents/execution.py` — current orchestrator
  - `audit draft 2.2` — god-module

  **Acceptance Criteria**:
  - [ ] `src/agents/execution/execution_core.py` exists
  - [ ] `ExecutionCore` composes the 4 extracted classes
  - [ ] `ExecutionAgent` is < 200 lines (down from 1377)
  - [ ] All existing tests pass
  - [ ] New tests for ExecutionCore

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: ExecutionAgent is now small
    Tool: Bash (wc)
    Preconditions: Refactor complete
    Steps:
      1. Get-Content src/agents/execution.py | Measure-Object -Line
    Expected Result: < 200 lines
    Failure Indicators: > 200 lines
    Evidence: .omo/evidence/task-39-execution-line-count.txt
  ```

  **Commit**: YES
  - Message: `refactor(execution): extract ExecutionCore orchestrator, ExecutionAgent is now thin wrapper`
  - Files: `src/agents/execution.py`, `src/agents/execution/execution_core.py` (new), tests

- [ ] 40. Update all callers (strategy_gen, risk_mgmt, reconciliation) for new ExecutionAgent API

  **What to do**:
  - After Task 39, the ExecutionAgent public API should be unchanged, but verify by searching for all callers
  - Read `src/agents/strategy_gen.py`, `src/agents/risk_mgmt.py`, `src/agents/reconciliation.py`
  - For each caller, verify it still uses the public API correctly
  - If any caller uses private attributes (`_paper_trading`, `_broker`, `_open_orders`), update to use public methods
  - Add tests for the new public API

  **Must NOT do**:
  - Do NOT change the public API of `ExecutionAgent` (only internal)
  - Do NOT skip verifying every caller

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` — caller updates
  - **Skills**: python, refactoring
  - **Why**: Many files, needs verification

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6
  - **Blocks**: None
  - **Blocked By**: Task 39

  **References**:
  - `src/agents/strategy_gen.py` — uses execution
  - `src/agents/risk_mgmt.py` — uses execution
  - `src/agents/reconciliation.py` — uses execution
  - `src/main.py` — uses execution via system

  **Acceptance Criteria**:
  - [ ] No caller uses private attributes of `ExecutionAgent`
  - [ ] All callers use public methods
  - [ ] All existing tests pass
  - [ ] New tests for caller interactions

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: No private attribute access from outside execution
    Tool: Bash (grep)
    Preconditions: Refactor complete
    Steps:
      1. Select-String -Path "src/**/*.py" -Pattern "execution\._[a-z]" -Recurse
      2. Where-Object { $_.Path -notlike "*/agents/execution.py" -and $_.Path -notlike "*/agents/execution/*" }
    Expected Result: No results (no private access)
    Failure Indicators: Any matches outside execution.py and its submodules
    Evidence: .omo/evidence/task-40-no-private-access.txt
  ```

  **Commit**: YES
  - Message: `refactor: update all callers of ExecutionAgent to use public API`
  - Files: `src/agents/strategy_gen.py`, `src/agents/risk_mgmt.py`, `src/agents/reconciliation.py`, `src/main.py`, tests

- [ ] 41. Verify all 329 existing tests still pass after execution.py split

  **What to do**:
  - Run full test suite: `pytest tests/ -v`
  - Document any test failures
  - For each failure, either fix the test or fix the code (prefer fixing the code)
  - Verify coverage still ≥80% (from Task 14)
  - Add a test specifically for the refactored ExecutionCore that mirrors the original god-module test
  - Update `docs/ARCHITECTURE.md` to reflect the new structure

  **Must NOT do**:
  - Do NOT delete failing tests (fix them)
  - Do NOT lower the coverage threshold

  **Recommended Agent Profile**:
  - **Category**: `deep` — full test verification
  - **Skills**: python, testing
  - **Why**: Comprehensive verification

  **Parallelization**:
  - **Can Run In Parallel**: NO (verification task)
  - **Parallel Group**: Wave 6 (last task)
  - **Blocks**: Wave 7 (Phase 2 depends on refactor)
  - **Blocked By**: Tasks 35-40

  **References**:
  - `tests/` — all 55+ test files
  - `pyproject.toml:79-81` — pytest config
  - `audit draft 2.2` — refactor goal

  **Acceptance Criteria**:
  - [ ] All 329+ existing tests pass
  - [ ] Coverage ≥ 80%
  - [ ] No new test failures introduced
  - [ ] `docs/ARCHITECTURE.md` updated with new structure
  - [ ] New test for `ExecutionCore` (mirror of original)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Full test suite passes
    Tool: Bash (pytest)
    Preconditions: All Wave 6 refactors done
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ 2>&1 | Select-String "passed"
    Expected Result: ≥329 passed, 0 failed
    Failure Indicators: Any failure or error
    Evidence: .omo/evidence/task-41-full-test-suite.txt
  ```

  **Commit**: YES
  - Message: `test: verify all 329 tests pass after execution.py refactor`
  - Files: any test fixes, `docs/ARCHITECTURE.md`

- [ ] 42. Implement broker reconciliation on startup (compare DB vs Kite open orders)

  **What to do**:
  - Read `src/agents/reconciliation.py` (existing, 6225 bytes)
  - Read `src/system.py:127-162` (current startup)
  - Add a `reconcile_on_startup()` method on `ReconciliationAgent` that:
    - Compares local order DB with Kite's open orders (via KiteBroker.get_orders())
    - Reconciles positions: local vs Kite positions
    - Emits `RECONCILIATION_RESULT` event with deltas
    - Logs mismatches at WARNING level
    - Raises `ReconciliationMismatch` if deltas exceed threshold
  - Wire into `system.py:start()` before agents start
  - Add tests with mock broker responses

  **Must NOT do**:
  - Do NOT reconcile if Kite credentials are missing (skip silently in paper mode)
  - Do NOT auto-correct mismatches (only log and alert)
  - Do NOT block startup on a mismatch (degrade gracefully)

  **Recommended Agent Profile**:
  - **Category**: `deep` — broker integration
  - **Skills**: python, async, kite-api
  - **Why**: Real money, needs care

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41 (Wave 6 refactor done)

  **References**:
  - `src/agents/reconciliation.py` — existing
  - `src/system.py:127-162` — startup sequence
  - `src/connectors/kite/broker.py` — Kite broker
  - `plan.md:289` — "Implement broker reconciliation on startup"

  **Acceptance Criteria**:
  - [ ] `ReconciliationAgent.reconcile_on_startup()` method exists
  - [ ] Called in `system.py:start()` before agents start
  - [ ] Skips silently if Kite creds missing
  - [ ] Logs mismatches at WARNING
  - [ ] Emits `RECONCILIATION_RESULT` event
  - [ ] Tests with mock broker (match, mismatch, no-creds)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Reconciliation detects mismatch
    Tool: Bash (pytest)
    Preconditions: Mock broker with extra order
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "reconcile_on_startup" -v 2>&1 | Select-String "PASSED"
    Expected Result: Tests for match, mismatch, no-creds all pass
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-42-reconciliation-on-startup.txt
  ```

  **Commit**: YES
  - Message: `feat(reconciliation): add reconcile_on_startup, compare DB vs broker on system start`
  - Files: `src/agents/reconciliation.py`, `src/system.py`, `src/connectors/kite/broker.py`, tests

- [ ] 43. Add backtest gate for ReflectionEngine mutations

  **What to do**:
  - Read `src/agents/reflection_engine.py` (existing, 27KB)
  - Add a `BacktestGate` class that:
    - Takes a strategy mutation (candiate config)
    - Runs backtest on last 30 days of data
    - Compares to baseline Sharpe
    - Allows mutation only if Sharpe improves by >5% AND max drawdown doesn't increase
  - Wire into the candidate approval flow
  - Add env flag `TRA_REFLECTION_BACKTEST_GATE_ENABLED=true` (default on in live, off in paper)
  - Add tests

  **Must NOT do**:
  - Do NOT block mutation if backtest data is missing (log and allow)
  - Do NOT run the gate on every candidate (only on approve)
  - Do NOT silently change the gate threshold

  **Recommended Agent Profile**:
  - **Category**: `deep` — strategy validation
  - **Skills**: python, async, backtesting
  - **Why**: Affects live strategy behavior

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/agents/reflection_engine.py` — existing
  - `src/backtest/engine.py` — backtest runner
  - `src/monitoring/attribution.py` — Sharpe calculation
  - `plan.md:291` — "Add mandatory backtest gate before ReflectionEngine mutations"

  **Acceptance Criteria**:
  - [ ] `BacktestGate` class in `src/agents/reflection_engine/`
  - [ ] Gate is called in candidate approval flow
  - [ ] Configurable threshold via env
  - [ ] Tests for: improve, degrade, no-data
  - [ ] Logs gate decisions

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: BacktestGate rejects degradation
    Tool: Bash (pytest)
    Preconditions: Mock backtest with known result
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "backtest_gate" -v 2>&1 | Select-String "PASSED"
    Expected Result: All gate tests pass (improve → allow, degrade → reject)
    Failure Indicators: Degradation allowed
    Evidence: .omo/evidence/task-43-backtest-gate.txt
  ```

  **Commit**: YES
  - Message: `feat(reflection): add BacktestGate before mutating live strategies`
  - Files: `src/agents/reflection_engine.py`, `src/agents/reflection_engine/backtest_gate.py` (new), tests

- [ ] 44. Add multi-timeframe confirmation (1m + 15m alignment)

  **What to do**:
  - Read `src/agents/strategy_gen.py` (762 lines)
  - Read `src/utils/timeframe.py` (existing timeframe utility)
  - Add a `MultiTimeframeFilter` that:
    - Requires 1m signal AND 15m trend to agree (both long or both short)
    - Uses EMA200 on 15m as trend indicator
    - Blocks signal if timeframes disagree
  - Wire into strategy_gen before signal emission
  - Add config: `multi_timeframe_enabled: bool = true`
  - Add tests

  **Must NOT do**:
  - Do NOT block all signals if 15m data is missing (log and allow 1m only)
  - Do NOT change the existing 1m signal logic

  **Recommended Agent Profile**:
  - **Category**: `deep` — strategy logic
  - **Skills**: python, async, technical-analysis
  - **Why**: Affects trade frequency

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/agents/strategy_gen.py` — signal generation
  - `src/utils/timeframe.py` — timeframe utility
  - `src/core/regime/ema200_filter.py` — existing EMA200
  - `plan.md:292` — "Add multi-timeframe confirmation: minute signal + 15-min trend alignment"

  **Acceptance Criteria**:
  - [ ] `MultiTimeframeFilter` class
  - [ ] 1m + 15m agreement required
  - [ ] Configurable on/off
  - [ ] Graceful when 15m data missing
  - [ ] Tests for: agree, disagree, no-15m-data

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: MultiTimeframeFilter blocks disagreement
    Tool: Bash (pytest)
    Preconditions: Mock 1m long + 15m short
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "multi_timeframe" -v 2>&1 | Select-String "PASSED"
    Expected Result: Tests pass (disagreement → blocked, agreement → allowed)
    Failure Indicators: Disagreement allowed
    Evidence: .omo/evidence/task-44-multi-timeframe.txt
  ```

  **Commit**: YES
  - Message: `feat(strategy): add multi-timeframe confirmation (1m + 15m alignment)`
  - Files: `src/agents/strategy_gen.py`, `src/utils/multi_timeframe.py` (new), tests

- [ ] 45. Replace 5bps flat slippage with depth-weighted order book model

  **What to do**:
  - Read `src/risk/costs.py` (existing cost model)
  - Replace the flat 5bps slippage with a depth-weighted model:
    - For each order, look up order book depth (top 5 levels)
    - Calculate weighted average fill price based on order size
    - If order size > available depth, slippage increases exponentially
  - Get order book from broker (Kite supports `get_quote` with depth)
  - Add config: `slippage_model: str = "depth_weighted"` (default) or `"flat"` (legacy)
  - Add tests

  **Must NOT do**:
  - Do NOT apply to paper fills (paper uses mid-price)
  - Do NOT use historical backtest data (need live order book)
  - Do NOT fail the order if depth is missing (use flat as fallback)

  **Recommended Agent Profile**:
  - **Category**: `deep` — market microstructure
  - **Skills**: python, async, order-book
  - **Why**: Affects execution quality

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/risk/costs.py` — current cost model
  - `src/connectors/kite/market_data.py` — Kite market data
  - `plan.md:293` — "Replace 5bps flat slippage with depth-weighted order book model"

  **Acceptance Criteria**:
  - [ ] `DepthWeightedSlippageModel` class
  - [ ] Uses order book depth
  - [ ] Falls back to flat on missing data
  - [ ] Tests with mock order book
  - [ ] Configurable

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Depth-weighted slippage handles large orders
    Tool: Bash (pytest)
    Preconditions: Mock order book
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "slippage" -v 2>&1 | Select-String "PASSED"
    Expected Result: Large orders get higher slippage than small
    Failure Indicators: All orders get same slippage
    Evidence: .omo/evidence/task-45-depth-weighted-slippage.txt
  ```

  **Commit**: YES
  - Message: `feat(costs): replace 5bps flat slippage with depth-weighted order book model`
  - Files: `src/risk/costs.py`, `src/agents/execution/execution_core.py`, tests

- [ ] 46. Add earnings calendar filter (block result day ±1)

  **What to do**:
  - Read `src/risk/earnings_filter.py` (existing)
  - Read `config/earnings_calendar.yaml` (referenced in settings.py:73)
  - Improve the filter to:
    - Block new entries on result day (D-0)
    - Also block day before (D-1) and day after (D+1) for safety
    - Allow exits to be closed normally
  - Add config: `earnings_block_days: int = 1` (0 = day-of only, 1 = ±1 day)
  - Auto-refresh calendar from a source (NSE BSE API, or manual YAML)
  - Add tests with sample calendar data

  **Must NOT do**:
  - Do NOT block existing positions (only new entries)
  - Do NOT fail if calendar is missing (warn and allow)
  - Do NOT download calendar in critical path (cache it)

  **Recommended Agent Profile**:
  - **Category**: `deep` — risk filter
  - **Skills**: python, async
  - **Why**: Affects trade frequency

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/risk/earnings_filter.py` — existing
  - `src/agents/risk_mgmt.py:40-41` — already uses filter
  - `config/earnings_calendar.yaml` — data file
  - `plan.md:294` — "Add earnings calendar filter (block new entries on result day ± 1 session)"

  **Acceptance Criteria**:
  - [ ] Filter blocks D-1, D-0, D+1
  - [ ] Configurable range
  - [ ] Calendar refresh mechanism
  - [ ] Tests for: in-range, out-of-range, missing-calendar

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Earnings filter blocks result day
    Tool: Bash (pytest)
    Preconditions: Mock calendar with today's date
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "earnings" -v 2>&1 | Select-String "PASSED"
    Expected Result: Test blocks entry on result day
    Failure Indicators: Entry allowed on result day
    Evidence: .omo/evidence/task-46-earnings-filter.txt
  ```

  **Commit**: YES
  - Message: `feat(risk): enhance earnings filter to block D-1 to D+1, add refresh mechanism`
  - Files: `src/risk/earnings_filter.py`, `config/earnings_calendar.yaml`, tests

- [ ] 47. Add correlation filter (block if portfolio correlation >0.7 with existing)

  **What to do**:
  - Read `src/risk/portfolio_optimizer.py` (existing, 10KB)
  - Add a `CorrelationFilter` class that:
    - Computes rolling 30-day return correlation between candidate and current positions
    - Blocks new signal if max correlation > 0.7 (configurable)
    - Uses Pearson correlation on daily returns
  - Wire into `risk_mgmt._validate_order` before position size check
  - Add config: `correlation_threshold: float = 0.7`
  - Add tests with synthetic return data

  **Must NOT do**:
  - Do NOT block on missing data (warn and allow)
  - Do NOT compute correlation for symbols with < 30 days of data
  - Do NOT use a single point estimate (use rolling)

  **Recommended Agent Profile**:
  - **Category**: `deep` — risk filter
  - **Skills**: python, pandas, statistics
  - **Why**: Affects diversification

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/risk/portfolio_optimizer.py` — existing
  - `src/agents/risk_mgmt.py:60-75` — risk validation
  - `plan.md:295` — "Add correlation filter: block new signal if portfolio correlation > 0.7 with existing"

  **Acceptance Criteria**:
  - [ ] `CorrelationFilter` class
  - [ ] Blocks when correlation > 0.7
  - [ ] Configurable threshold
  - [ ] Tests with: high-corr (block), low-corr (allow), no-data (allow+warn)

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Correlation filter blocks highly correlated entry
    Tool: Bash (pytest)
    Preconditions: Mock returns with 0.8 correlation
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "correlation" -v 2>&1 | Select-String "PASSED"
    Expected Result: Highly correlated entry blocked
    Failure Indicators: Allowed
    Evidence: .omo/evidence/task-47-correlation-filter.txt
  ```

  **Commit**: YES
  - Message: `feat(risk): add correlation filter, block new signal if portfolio correlation > 0.7`
  - Files: `src/risk/correlation_filter.py` (new), `src/agents/risk_mgmt.py`, tests

- [ ] 48. Wire stat_arb.py into StrategyGenAgent with proper pair selection

  **What to do**:
  - Read `src/strategies/stat_arb.py` (exists, 3426 bytes)
  - Read `src/agents/strategy_gen.py:9-13` (currently disabled in __init__.py ignore_list)
  - Enable stat_arb in `strategy_gen.py`
  - Implement proper pair selection:
    - Cointegration test (Engle-Granger or Johansen) on the universe
    - Select top N pairs by half-life of mean reversion
    - Use z-score for entry/exit signals
  - Add config: `stat_arb_max_pairs: int = 5`, `stat_arb_zscore_entry: float = 2.0`
  - Add tests with synthetic cointegrated pairs

  **Must NOT do**:
  - Do NOT use stat_arb if universe has < 5 symbols
  - Do NOT enter pairs with half-life > 30 days
  - Do NOT use both legs of a pair in other strategies (conflicting signals)

  **Recommended Agent Profile**:
  - **Category**: `deep` — strategy integration
  - **Skills**: python, statistics, pandas
  - **Why**: Complex strategy logic

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 7
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/strategies/stat_arb.py` — existing
  - `src/agents/strategy_gen.py:9-13` — currently disabled
  - `docs/active_strategy_set.md:13` — listed as disabled
  - `plan.md:297` — "Wire `src/strategies/stat_arb.py` into StrategyGenAgent with proper pair selection"

  **Acceptance Criteria**:
  - [ ] stat_arb enabled in strategy_gen
  - [ ] Cointegration test for pair selection
  - [ ] Z-score entry/exit logic
  - [ ] Configurable thresholds
  - [ ] Tests with synthetic pairs

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: stat_arb enters on z-score > 2
    Tool: Bash (pytest)
    Preconditions: Mock cointegrated pair
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "stat_arb" -v 2>&1 | Select-String "PASSED"
    Expected Result: Tests pass (z>2 → enter, z<0.5 → exit)
    Failure Indicators: Z-score signal not detected
    Evidence: .omo/evidence/task-48-stat-arb-wired.txt
  ```

  **Commit**: YES
  - Message: `feat(strategy): wire stat_arb into StrategyGenAgent with cointegration pair selection`
  - Files: `src/strategies/stat_arb.py`, `src/agents/strategy_gen.py`, `docs/active_strategy_set.md`, tests

- [ ] 49. Migrate event store to Postgres (concurrent readers, replay durability)

  **What to do**:
  - Read `src/event_store/postgres.py` (exists, 8516 bytes)
  - Read `src/event_store/sqlite.py` (current default)
  - Make Postgres the default for production (compose), keep SQLite for paper/test
  - Add migrations: schema versioning in `src/event_store/migrations/`
  - Add TimescaleDB hypertable for events table (compose already has timescale)
  - Add concurrent reader tests
  - Document migration path in `docs/OPERATIONS.md`

  **Must NOT do**:
  - Do NOT remove SQLite support (still needed for paper/test/dev)
  - Do NOT change the EventStore interface
  - Do NOT add Kafka (per audit: it's overengineered for now)

  **Recommended Agent Profile**:
  - **Category**: `deep` — DB migration
  - **Skills**: python, postgres, timescaledb
  - **Why**: Critical path for production

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41 (Wave 6 done)

  **References**:
  - `src/event_store/postgres.py` — existing
  - `src/event_store/sqlite.py` — current default
  - `docker-compose.yml:1-12` — TimescaleDB service
  - `plan.md:318` — "Migrate event store to Postgres for concurrent readers + replay durability"

  **Acceptance Criteria**:
  - [ ] `TRA_EVENT_STORE_TYPE=postgres` works in compose
  - [ ] Schema migrations apply cleanly
  - [ ] TimescaleDB hypertable created
  - [ ] Concurrent reader test passes
  - [ ] SQLite still works
  - [ ] `docs/OPERATIONS.md` documents migration

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Postgres event store handles concurrent readers
    Tool: Bash (pytest + docker)
    Preconditions: Postgres running
    Steps:
      1. cd "D:\projects\new trade"
      2. TRA_EVENT_STORE_TYPE=postgres pytest tests/test_event_store.py -v 2>&1 | Select-String "PASSED"
    Expected Result: All event store tests pass with Postgres backend
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-49-postgres-event-store.txt
  ```

  **Commit**: YES
  - Message: `feat(eventstore): migrate to Postgres + TimescaleDB, add schema migrations`
  - Files: `src/event_store/postgres.py`, `src/event_store/migrations/` (new), `docs/OPERATIONS.md`, tests

- [ ] 50. Add CNC/NRML product type support (overnight, swing)

  **What to do**:
  - Read `src/schemas/events.py` (ProductType enum, currently has MIS)
  - Add `CNC` (delivery, no auto square-off) and `NRML` (normal, F&O) to ProductType
  - Update `src/agents/execution.py` to handle CNC/NRML:
    - CNC: no square-off at 15:30, can hold overnight
    - NRML: similar to CNC for F&O
  - Add config: `default_product_type: str = "MIS"` (preserves current behavior)
  - Add UI in dashboard for product type selection per order
  - Add tests

  **Must NOT do**:
  - Do NOT auto-square CNC/NRML positions (the user is responsible)
  - Do NOT enable CNC/NRML by default (paper is MIS only)
  - Do NOT break existing MIS flow

  **Recommended Agent Profile**:
  - **Category**: `deep` — order types
  - **Skills**: python, broker-api
  - **Why**: Affects position lifecycle

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/schemas/events.py` — ProductType
  - `src/agents/risk_mgmt.py:20` — square-off time constant
  - `plan.md:319` — "CNC / NRML product type support for overnight and swing setups"

  **Acceptance Criteria**:
  - [ ] ProductType.CNC and ProductType.NRML added
  - [ ] ExecutionAgent handles CNC/NRML (no auto square-off)
  - [ ] Configurable default
  - [ ] Dashboard has product type selector
  - [ ] Tests for all 3 product types

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: CNC order doesn't auto square-off
    Tool: Bash (pytest)
    Preconditions: Mock execution
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "product_type" -v 2>&1 | Select-String "PASSED"
    Expected Result: CNC order not squared off at 15:30
    Failure Indicators: CNC order auto-squared
    Evidence: .omo/evidence/task-50-cnc-nrml-support.txt
  ```

  **Commit**: YES
  - Message: `feat(execution): add CNC and NRML product type support, no auto square-off`
  - Files: `src/schemas/events.py`, `src/agents/execution/execution_core.py`, `dashboard/server.py`, tests

- [ ] 51. Add PagerDuty/Telegram on-call for critical alerts

  **What to do**:
  - Read `monitor.py` (existing Telegram integration)
  - Read `src/agents/alert.py` (existing alert agent)
  - Add PagerDuty integration:
    - Use `pagerduty` Python package or REST API directly
    - Trigger on CRITICAL alerts (system down, kill switch, broker disconnect)
  - Add Telegram integration via `alert.py`:
    - Use existing `TRA_TELEGRAM_BOT_TOKEN` and `TRA_TELEGRAM_CHAT_ID` from settings
    - Send alert on WARNING and CRITICAL
  - Add env flag: `TRA_PAGERDUTY_ROUTING_KEY` (already in settings.py:78)
  - Add tests with mock Telegram/PagerDuty

  **Must NOT do**:
  - Do NOT use PagerDuty for low-severity alerts (spam)
  - Do NOT hardcode any chat IDs or routing keys
  - Do NOT fail the system if alert delivery fails (log and continue)

  **Recommended Agent Profile**:
  - **Category**: `deep` — alerting integration
  - **Skills**: python, async, integrations
  - **Why**: On-call critical

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `monitor.py:1-241` — existing Telegram integration
  - `src/agents/alert.py:1-200` — existing alert agent
  - `src/config/settings.py:78` — `pagerduty_routing_key`
  - `plan.md:316-317` — PagerDuty / Telegram on-call

  **Acceptance Criteria**:
  - [ ] PagerDuty alert on CRITICAL events
  - [ ] Telegram alert on WARNING + CRITICAL
  - [ ] Configurable via env vars
  - [ ] No hardcoded secrets
  - [ ] Tests with mock APIs

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: PagerDuty triggered on kill switch
    Tool: Bash (pytest)
    Preconditions: Mock PagerDuty
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "pagerduty" -v 2>&1 | Select-String "PASSED"
    Expected Result: Kill switch trigger calls PagerDuty API
    Failure Indicators: No PagerDuty call
    Evidence: .omo/evidence/task-51-pagerduty-telegram.txt
  ```

  **Commit**: YES
  - Message: `feat(alerts): integrate PagerDuty for critical alerts, Telegram for warning+`
  - Files: `src/agents/alert.py`, `src/utils/pagerduty.py` (new), tests

- [ ] 52. Add secret vault integration (HashiCorp Vault or AWS)

  **What to do**:
  - Read `src/utils/vault.py` (exists, 90 lines, partial)
  - Read `src/config/settings.py:96-131` (eager load)
  - Complete the integration:
    - Add support for all 16 sensitive env vars (already started)
    - Add health check endpoint to verify vault connectivity at startup
    - Add graceful degradation: if vault is down, fall back to env vars (with WARNING)
    - Add test mode: `TRA_VAULT_PROVIDER=test` uses fake vault (in-memory dict)
  - Add docs in `docs/OPERATIONS.md` on how to set up Vault
  - Add tests for all 3 providers (vault, aws, test)

  **Must NOT do**:
  - Do NOT hardcode vault URLs (env var only)
  - Do NOT fail startup if vault is unreachable (degrade gracefully)
  - Do NOT log secret values (only metadata: "loaded 16 secrets")

  **Recommended Agent Profile**:
  - **Category**: `deep` — secret management
  - **Skills**: python, security, hvac, boto3
  - **Why**: Production security

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/utils/vault.py:1-90` — existing
  - `src/config/settings.py:96-131` — eager load
  - `plan.md:317` — "Secret vault for Kite token rotation"

  **Acceptance Criteria**:
  - [ ] All 3 providers work (vault, aws, test)
  - [ ] Health check at startup
  - [ ] Graceful degradation
  - [ ] No hardcoded URLs
  - [ ] No secret value logging
  - [ ] Tests for all providers

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Vault health check passes
    Tool: Bash (pytest)
    Preconditions: Mock vault
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "vault" -v 2>&1 | Select-String "PASSED"
    Expected Result: All vault tests pass (3 providers + health check)
    Failure Indicators: Any failure
    Evidence: .omo/evidence/task-52-vault-integration.txt
  ```

  **Commit**: YES
  - Message: `feat(security): complete vault integration with health check, graceful degradation`
  - Files: `src/utils/vault.py`, `src/config/settings.py`, `docs/OPERATIONS.md`, tests

- [ ] 53. Add microstructure signal (order flow imbalance)

  **What to do**:
  - Read `src/strategies/microstructure.py` (exists, 3961 bytes)
  - Enable it in `src/agents/strategy_gen.py`
  - Add full order book integration from Kite WebSocket
  - Implement order flow imbalance (OFI) signal:
    - Track bid/ask volume changes at top 5 levels
    - Compute OFI = (bid_volume_change) - (ask_volume_change)
    - Normalize by total volume
  - Use OFI as a confirmation signal (not primary)
  - Add config: `microstructure_enabled: bool = false` (off by default, needs order book)
  - Add tests with mock order book deltas

  **Must NOT do**:
  - Do NOT enable by default (requires full order book, which Kite charges extra for)
  - Do NOT use stale order book data (>1s old)
  - Do NOT use OFI as the only signal (confirmation only)

  **Recommended Agent Profile**:
  - **Category**: `deep` — microstructure
  - **Skills**: python, market-microstructure, order-book
  - **Why**: Complex signal logic

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/strategies/microstructure.py` — existing
  - `src/connectors/kite/market_data.py` — Kite order book
  - `plan.md:309-312` — "Replace or augment lagging indicator ensemble with at least one of: Microstructure signal"

  **Acceptance Criteria**:
  - [ ] Microstructure strategy enabled (configurable)
  - [ ] Order flow imbalance signal implemented
  - [ ] Uses real order book data
  - [ ] Confirmation signal only (not primary)
  - [ ] Tests with mock data

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: OFI signal detects buying pressure
    Tool: Bash (pytest)
    Preconditions: Mock order book with bid pressure
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "microstructure" -v 2>&1 | Select-String "PASSED"
    Expected Result: OFI positive when bid volume increases
    Failure Indicators: OFI flat
    Evidence: .omo/evidence/task-53-microstructure-signal.txt
  ```

  **Commit**: YES
  - Message: `feat(strategy): add microstructure OFI signal with order book integration`
  - Files: `src/strategies/microstructure.py`, `src/agents/strategy_gen.py`, tests

- [ ] 54. Add Kelly/fractional Kelly position sizing

  **What to do**:
  - Read `src/risk/kelly_sizing.py` (exists, 5155 bytes)
  - Read `src/risk/__init__.py` (where it's exposed)
  - Wire Kelly into the risk management flow:
    - Compute Kelly fraction from strategy win rate and avg win/loss
    - Apply fractional Kelly (default 0.5x, configurable) for safety
    - Use min(Kelly, fixed_fraction) as the actual position size
  - Add config: `risk_sizing_method: str = "kelly"` (already in settings.py:76), `kelly_fraction: float = 0.5`
  - Add tests

  **Must NOT do**:
  - Do NOT use full Kelly (too aggressive, can blow up)
  - Do NOT use Kelly with < 30 trade samples (unreliable)
  - Do NOT fall back to zero position if Kelly is negative (use minimum)

  **Recommended Agent Profile**:
  - **Category**: `deep` — position sizing
  - **Skills**: python, statistics
  - **Why**: Affects position size

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `src/risk/kelly_sizing.py` — existing
  - `src/risk/__init__.py` — exports
  - `src/config/settings.py:76` — `risk_sizing_method`
  - `plan.md:314` — "Kelly / fractional Kelly position sizing replacing fixed 1% rule"

  **Acceptance Criteria**:
  - [ ] Kelly sizing wired into risk_mgmt
  - [ ] Fractional Kelly default 0.5x
  - [ ] Fallback to fixed if < 30 samples
  - [ ] Tests for: enough-data, no-data, negative-kelly

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Kelly sizing uses fractional Kelly
    Tool: Bash (pytest)
    Preconditions: Mock trade history
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "kelly" -v 2>&1 | Select-String "PASSED"
    Expected Result: Position size = fractional_kelly * full_kelly
    Failure Indicators: Position size = full_kelly (not fractional)
    Evidence: .omo/evidence/task-54-kelly-sizing.txt
  ```

  **Commit**: YES
  - Message: `feat(risk): wire Kelly/fractional Kelly position sizing into risk management`
  - Files: `src/risk/kelly_sizing.py`, `src/agents/risk_mgmt.py`, tests

- [ ] 55. Add SEBI algo trading compliance review checklist

  **What to do**:
  - Read `SECURITY.md` and existing risk docs
  - Research SEBI algo trading requirements (as of 2026):
    - Algo ID registration
    - Broker approval
    - Order-to-trade ratio limits
    - Audit trail requirements
    - Risk management requirements
  - Create `docs/COMPLIANCE_SEBI.md` with:
    - Requirements checklist
    - Current compliance status (what we have, what we lack)
    - Action items before going live
  - Add config flags for compliance: `sebi_algo_id: str = ""`, `broker_approved: bool = false`
  - Add pre-flight check in `main.py` that warns if live mode but not compliant
  - Add tests

  **Must NOT do**:
  - Do NOT make legal claims (this is a checklist, not legal advice)
  - Do NOT enable live trading without explicit user compliance confirmation
  - Do NOT store SEBI algo ID in env (use Vault, per Task 52)

  **Recommended Agent Profile**:
  - **Category**: `writing` — compliance doc + checks
  - **Skills**: documentation, compliance
  - **Why**: Legal/policy, needs care

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 8
  - **Blocks**: None
  - **Blocked By**: Task 41

  **References**:
  - `SECURITY.md` — existing
  - `plan.md:320` — "SEBI algo trading registration compliance review"
  - SEBI circulars (research via web search)

  **Acceptance Criteria**:
  - [ ] `docs/COMPLIANCE_SEBI.md` exists, 200-500 lines
  - [ ] Requirements checklist with current status
  - [ ] Pre-flight check in main.py
  - [ ] Config flags for SEBI algo ID, broker approval
  - [ ] Tests for pre-flight check

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Pre-flight check warns on missing algo ID
    Tool: Bash (pytest)
    Preconditions: TRA_LIVE_TRADING_ENABLED=true, no algo ID
    Steps:
      1. cd "D:\projects\new trade"
      2. pytest tests/ -k "compliance" -v 2>&1 | Select-String "PASSED"
    Expected Result: Pre-flight warns about missing SEBI algo ID
    Failure Indicators: No warning
    Evidence: .omo/evidence/task-55-sebi-compliance.txt
  ```

  **Commit**: YES
  - Message: `docs(compliance): add SEBI algo trading compliance checklist and pre-flight check`
  - Files: `docs/COMPLIANCE_SEBI.md` (new), `src/main.py`, `src/config/settings.py`, tests

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.

- [ ] F1. Plan Compliance Audit — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in `.omo/evidence/`. Compare deliverables against plan. Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. Code Quality Review — `unspecified-high`
  Run `ruff check` + `ruff format --check` + `mypy --strict` + `pytest`. Review all changed files for: `Any` casts, `type: ignore`, empty catches, print statements in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp). Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. Real Manual QA — `unspecified-high` (plus playwright if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.omo/evidence/final-qa/`. Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. Scope Fidelity Check — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes. Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: 6 atomic commits, one per task (`chore(security): ...`, `chore(deps): ...`, etc.)
- **Wave 2**: 7 atomic commits, one per doc (`docs(init): ...`, `docs(changelog): ...`, etc.)
- **Wave 3**: 7 atomic commits (CI changes, test improvements)
- **Wave 4**: 7 atomic commits (one per metric/alert/feature)
- **Wave 5**: 7 atomic commits (one per refactor)
- **Wave 6**: 7 atomic commits (extraction steps, then verification)
- **Wave 7**: 7 atomic commits (one per Phase 2 feature)
- **Wave 8**: 7 atomic commits (one per Phase 3 feature)
- **Total**: 55 atomic commits, each with passing tests, descriptive message, and evidence file

**Commit message format:**
```
<type>(<scope>): <subject>

<body explaining what and why>

<footer with evidence reference>
```

**Pre-commit checks** (all atomic commits):
- `ruff check src/ tests/`
- `ruff format --check src/ tests/`
- `mypy src/`
- `pytest tests/ -x` (fail fast)

---

## Success Criteria

### Verification Commands
```bash
# All quality gates pass
ruff check src/ tests/                                          # Expected: All checks passed
ruff format --check src/ tests/                                 # Expected: would reformat 0 files
mypy --strict src/                                              # Expected: Success: no issues found
pytest tests/ --cov=src --cov-fail-under=80                     # Expected: ≥329 passed, ≥80% coverage
gitleaks detect --source . --no-git                             # Expected: no leaks found
pip-audit -r pyproject.toml                                     # Expected: no high/critical vulnerabilities

# All new docs exist
test -f docs/INDEX.md && test -f docs/ARCHITECTURE.md \
  && test -f docs/RUNBOOK.md && test -f docs/CONTRIBUTING.md \
  && test -f docs/OPERATIONS.md && test -f docs/COMPLIANCE_SEBI.md  # Expected: all exist

# All metrics exported
curl -s http://localhost:8080/metrics | grep -E "trading_(pnl_daily|exposure_total|open_positions|attribution_pnl_total|slippage_bps|fill_rate)"  # Expected: all present

# All alerts defined
promtool check rules prometheus_alerts.yml                       # Expected: success

# No leaked secrets
git log --all -p | grep -E "TRA_KITE_API_KEY\s*=\s*[a-zA-Z0-9]{16,}"  # Expected: no output

# No leaked test artifacts
ls state/ | grep -E "(probe|test)_.*\.db"                       # Expected: no output

# 5-day paper run still healthy
curl -s http://localhost:8080/health                            # Expected: 200 OK with all agents running
```

### Final Checklist
- [ ] All "Must Have" items from Work Objectives present
- [ ] All "Must NOT Have" patterns absent from codebase
- [ ] All 55 tasks completed with QA evidence
- [ ] All 4 final verification tasks (F1-F4) returned APPROVE
- [ ] 5-day paper run criteria still pass (per `docs/live_trading_gate.md`)
- [ ] 30-day paper run gate criteria on track
- [ ] All new docs reviewed by user
- [ ] All atomic commits pushed to remote
- [ ] No new bugs introduced (per F1 audit)
- [ ] No scope creep (per F4 audit)

