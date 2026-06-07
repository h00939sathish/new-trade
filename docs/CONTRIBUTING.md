# Contributing

> **Audience**: engineers contributing code to the `new-trade` paper
> trading system. This guide covers local setup, dev workflow, testing,
> code style, and the extension patterns for adding strategies, brokers,
> and agents. For the system architecture, see
> [`ARCHITECTURE.md`](ARCHITECTURE.md). For day-to-day operations, see
> [`RUNBOOK.md`](RUNBOOK.md).

---

## Table of contents

1. [Setup](#1-setup)
2. [Dev workflow](#2-dev-workflow)
3. [Testing](#3-testing)
4. [Code style](#4-code-style)
5. [Add a strategy](#5-add-a-strategy)
6. [Add a broker](#6-add-a-broker)
7. [Add an agent](#7-add-an-agent)
8. [First PR checklist](#8-first-pr-checklist)

---

## 1. Setup

### Prerequisites

- **Python 3.12.x** (the project pins `>=3.12,<3.13`; 3.13+ is **not**
  supported). Verify with `python --version`.
- **Git** for source control.
- **Docker Desktop** (optional but recommended) for running
  `postgres` + `redis` locally without installing them natively.
- **Node 20 LTS** (only for dashboard frontend work) — the
  Dockerfile uses `node:20` because `node:20-alpine` lacks
  `node-gyp` for `better-sqlite3`.

### First-time install

```bash
# 1. Clone
git clone https://github.com/aisathish07/new-trade.git
cd new-trade

# 2. Create venv
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install (core + dev + dashboard + vault extras)
pip install -e ".[dev,dashboard,vault]"

# 4. Copy env template
cp .env.example .env
# Edit .env with your MONITOR_BOT_TOKEN / MONITOR_CHAT_ID and
# any broker creds. Never commit this file.

# 5. (Optional) Start postgres + redis
make db-up

# 6. Run tests
make test
```

### Optional extras

`pyproject.toml` defines 6 extras. Pick what you need:

| Extra | Installs | When to use |
|---|---|---|
| `dev` | pytest, pytest-asyncio, pytest-cov, pytest-mock, ruff, mypy, pre-commit | Always (CI requires it) |
| `dashboard` | fastapi, uvicorn | Running `dashboard/server.py` |
| `kite` | kiteconnect | Working on `src/connectors/kite/` |
| `ml` | scikit-learn, lightgbm, torch | Working on `src/ml/` or `src/strategies/ml_regime.py` |
| `streaming` | apache-flink | Reserved; not in hot path |
| `vault` | boto3, hvac | When `TRA_VAULT_BACKEND=aws` or `hvac` |

Examples:
```bash
# Just dev work
pip install -e ".[dev]"

# Strategy + ML work
pip install -e ".[dev,ml]"

# Kite broker work
pip install -e ".[dev,kite,dashboard]"

# Vault work
pip install -e ".[dev,vault]"
```

### Pre-commit hook (credential scan)

The repo ships a pre-commit hook at `.githooks/pre-commit` that
scans staged files for credential patterns (Kite/Groww/Angel
tokens, JWTs, generic API keys / secrets / passwords). Install
once after cloning:

```bash
git config core.hooksPath .githooks
```

The hook will block any commit that includes a credential
pattern. It is a **safety net**, not a substitute for not
committing secrets; the recent `k1bpotx2f133yrms` leak
(see [`SECURITY.md`](../SECURITY.md)) is exactly what this hook
is designed to catch.

> The hook is currently a **single PowerShell script** that
> checks string patterns. CI also runs
> [`gitleaks/gitleaks-action@v2`](../.github/workflows/ci.yml)
> on every push and pull request as a deeper second-layer
> scan (full git history, more patterns). The two are
> complementary: the pre-commit hook is fast and local;
> gitleaks in CI is comprehensive and blocks the PR.

---

## 2. Dev workflow

### Make targets

`Makefile` is the entry point for common dev commands:

| Target | Command | What it does |
|---|---|---|
| `install` | `make install` | `pip install -e .` + `[dev,kite]` |
| `dev` | `make dev` | `pip install -e ".[dev,kite,ml]"` |
| `lint` | `make lint` | `ruff check src/` + `mypy src/` |
| `test` | `make test` | `pytest tests/ -v --cov=src` |
| `db-up` | `make db-up` | `docker compose up -d postgres redis` |
| `db-down` | `make db-down` | `docker compose down` |
| `run-market-intel` | `make run-market-intel` | `python -m src.agents.market_intel` |
| `run-strategy-gen` | `make run-strategy-gen` | `python -m src.agents.strategy_gen` |
| `run-risk-mgmt` | `make run-risk-mgmt` | `python -m src.agents.risk_mgmt` |
| `run-execution` | `make run-execution` | `python -m src.agents.execution` |
| `replay` | `make replay` | `python scripts/replay_events.py` |
| `clean` | `make clean` | `rm -rf __pycache__ .pytest_cache *.egg-info` + find delete |

`make test` is the only target you need to run repeatedly
during development. The full lint + type-check + test is run in
CI (see `.github/workflows/ci.yml`).

The `test` job runs on **both** `ubuntu-latest` and
`windows-latest` as a matrix; both must pass before a PR can
be merged. If a test passes locally on Windows but fails on
Linux (or vice versa), the most common cause is a hard-coded
path separator (`/` vs `\`) — use `pathlib.Path` instead of
string concatenation.

### Branch + commit conventions

- **Branch from `master`**. Use a descriptive name:
  - `feat/<short-desc>` for new features
  - `fix/<short-desc>` for bug fixes
  - `chore/<short-desc>` for tooling / docs
  - `audit/<task-num>` for the audit remediation work
- **Commit messages**: imperative mood, ≤ 72 char subject, body
  explains the *why*. Example:
  ```
  feat(strategies): add vwap_reversion strategy
  
  Mirrors the volume-weighted-average-price deviation that
  worked in backtest 2026-05-30; cold-start = 20 candles.
  ```
- **One logical change per commit.** Squash fixups locally; do
  not push `--force` to `master` (see Section 8).

### Local paper-run dev

For end-to-end testing without committing to the 5-day burn-in,
run the system locally:

```bash
make db-up           # postgres + redis
python -m src.main   # boots TradingSystem + all agents
```

The local run uses `state/trading_events.db` (SQLite) by
default; do not point it at a Postgres DSN that the burn-in is
also writing to, or you'll interleave events.

---

## 3. Testing

### Running tests

```bash
# All tests, with coverage
make test

# Just one file
pytest tests/test_strategy_gen.py -v

# Just one test
pytest tests/test_strategy_gen.py::test_vwap_warmup_blocks_signal -v

# By keyword
pytest tests/ -v -k "kill_switch"

# With pdb on failure
pytest tests/ -v --pdb
```

### Test conventions

- **Test files** mirror source: `tests/test_<module>.py` for
  `src/<module>.py`. Exceptions: integration tests live under
  `tests/integration/`.
- **Test names** are sentences: `test_<thing>_<expected>`,
  e.g., `test_kill_switch_fires_on_daily_loss_limit`.
- **Async tests** are auto-detected (`asyncio_mode = "auto"` in
  `pyproject.toml`); you do not need `@pytest.mark.asyncio`.
- **Database isolation**: every test that touches SQLite must
  use `tmp_path` (see Section 5 of [`RUNBOOK.md`](RUNBOOK.md))
  and clean up. Tests must NOT write to `state/*.db` (the
  gitignored shared state). The plan's Wave 3 Task 20 will
  enforce this with a fixture; until then, audit PRs for
  `state/test_*.db` leaks.
- **Determinism**: backtest tests must pin a date range and a
  fixed seed; do not assert exact PnL numbers without a known
  fixture.

### Coverage

`make test` produces a coverage report. The current target is
**80 %** (`--cov-fail-under=80`), enforced in CI starting Wave
3 Task 14. Locally, missing coverage shows as:

```
---------- coverage: platform win32, python 3.12.x -----------
Name                          Stmts   Miss  Cover
-------------------------------------------------
src/agents/execution.py         312     48    85%
...
```

To browse an HTML report:

```bash
pytest tests/ --cov=src --cov-report=html
# Open htmlcov/index.html
```

---

## 4. Code style

### Lint + format

- **Ruff** for lint + import-sort: `ruff check src/`
  (configured in `pyproject.toml` `[tool.ruff.lint]` with
  `select = ["E", "F", "I", "N", "W", "UP"]`).
  The Wave 5 audit will add `B` (bugbear), `C4` (comprehensions),
  `SIM` (simplify), `PT` (pytest), `TID` (tidy imports).
- **mypy** for types: `mypy src/`. The current config has 12
  `disable_error_code` entries (see `pyproject.toml:68-81`);
  Wave 5 Task 28 will remove these to enable strict mode.
- **No formatter** is enforced yet (the codebase mixes `black`-
  style and `ruff format` style). Wave 3 Task 17 will add
  `ruff format --check` to CI.

### Conventions

- **Pydantic v2** for all data models (`src/schemas/`). Use
  `Field(...)` for required fields, `model_config = ConfigDict(extra="forbid")`
  for strict validation.
- **Async-first**. All I/O — broker calls, DB writes, HTTP —
  is `async`. Sync code in `src/agents/` is a bug.
- **No `print()`** in `src/`. Use `logger = logging.getLogger(__name__)`
  and emit structured records. The `Rich` console output lives
  in `src/monitoring/dashboard.py` (CLI only) and
  `src/monitoring/http_dashboard.py` (HTML).
- **No `as any`, no `@ts-ignore` analogue.** Strict typing is
  the goal; silence type errors with `cast()` or a real
  annotation, not suppression.
- **Type hints on every public function**. Internal helpers
  may use `# type: ignore[arg-type]` for genuinely-untyped
  third-party libs (see `ignore_missing_imports = true`).

### What NOT to do

- Do **not** edit `state/*.db` files in tests. Use `tmp_path`.
- Do **not** add Rust / Go / Kafka code. The previous `init.md`
  claimed these would exist; they were never built, and the
  audit-remediation plan explicitly forbids re-introducing
  them. See [`ARCHITECTURE.md`](ARCHITECTURE.md) § "What is
  NOT in the architecture".
- Do **not** commit `.env` or any file matching the patterns
  in `.githooks/pre-commit`. If you accidentally stage one,
  unstage with `git restore --staged <file>` and move the
  secret to your local `.env`.
- Do **not** push `--force` to `master`. Rebase your own
  feature branch freely; never rewrite shared history.

---

## 5. Add a strategy

Strategies live in `src/strategies/`. They are *pure* — no
shared state, no I/O. Each strategy evaluates OHLCV and returns
a signal dict.

### Base class

`src/strategies/base.py` defines `Strategy` (17 lines). The
abstract `evaluate()` method is the only thing you must
implement:

```python
class Strategy:
    name: str
    data_type: str = "any"     # "tick" | "candle" | "any"
    timeframe: str = "minute"  # "minute" | "5minute" | "15minute" | "day"

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None: ...
```

### Minimal example

```python
# src/strategies/my_new_strategy.py
import statistics
from src.strategies.base import Strategy


class MyNewStrategy(Strategy):
    name = "my_new_strategy"
    data_type = "candle"
    timeframe = "minute"

    def __init__(self, lookback: int = 20, z_entry: float = 2.0) -> None:
        self.lookback = lookback
        self.z_entry = z_entry

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        # Cold-start
        if len(prices) < self.lookback:
            return None
        window = prices[-self.lookback:]
        mean = statistics.mean(window)
        stdev = statistics.stdev(window)
        if stdev == 0:
            return None
        z = (prices[-1] - mean) / stdev
        if abs(z) < self.z_entry:
            return None
        side = "long" if z < 0 else "short"  # mean reversion
        return {
            "side": side,
            "strength": min(1.0, abs(z) / (self.z_entry * 2)),
            "meta": {"z_score": z, "lookback": self.lookback},
        }
```

### Wiring

1. Add the class to `src/strategies/__init__.py`'s `ignore_list`
   (or remove the entry if it was a draft) so it gets imported.
2. Register the strategy in `src/config/strategy_config.py`:
   ```python
   from src.strategies.my_new_strategy import MyNewStrategy
   DEFAULT_CONFIG = {
       "active": {
           "my_new_strategy": {"class": MyNewStrategy, "weight": 0.20, ...},
       },
   }
   ```
3. Write a test in `tests/test_my_new_strategy.py`:
   - Cold-start: `assert evaluate(...) is None` when `len(prices) < lookback`
   - No signal: `assert evaluate(...) is None` when `|z| < z_entry`
   - Signal: `assert evaluate(...)["side"] in {"long", "short"}`
4. Re-balance the active weights so they sum to 1.0 (the
   `StrategyGenAgent` does not auto-normalize).
5. **During the 5-day burn-in window, do not change the
   active strategy set** — the gate is for *baseline*
   performance.

---

## 6. Add a broker

Brokers live in `src/connectors/<broker_name>/`. The pattern is
a triplet of `client`, `market_data`, and (optionally) `broker`
modules, with an `__init__.py` that exports them. The existing
examples are `kite/`, `angel/`, `groww/`, and `jugaad/`.

### Module layout

```
src/connectors/my_broker/
├── __init__.py          # exports MyBrokerClient, MyBrokerMarketData, MyBrokerBroker
├── client.py            # auth + low-level HTTP/WS
├── market_data.py       # OHLCV + tick streams
└── broker.py            # order placement, modification, cancellation
```

### Pattern

- **`MyBrokerClient`** is the low-level wrapper. It handles
  auth (API key + secret + TOTP), rate limiting, and
  exponential-backoff retries. Use `httpx.AsyncClient` with
  connection pooling.
- **`MyBrokerMarketData`** is a `MarketDataProvider` that
  polls/WS-streams the broker API and emits OHLCV events on
  the bus.
- **`MyBrokerBroker`** is the order-routing interface, with
  methods `place_order`, `modify_order`, `cancel_order`,
  `get_order_status`, `get_positions`.

### Auth via TOTP (e.g., Groww-style)

```python
import pyotp
from src.utils.vault import get_secret

class MyBrokerClient:
    def __init__(self) -> None:
        self.api_key = get_secret("TRA_MYBROKER_API_KEY")
        self.api_secret = get_secret("TRA_MYBROKER_API_SECRET")
        self.totp_secret = get_secret("TRA_MYBROKER_TOTP_SECRET")

    def _totp(self) -> str:
        return pyotp.TOTP(self.totp_secret).now()
```

`get_secret` (in `src/utils/vault.py`) reads from env → file →
AWS Secrets Manager → HashiCorp Vault (the `[vault]` extra
provides `boto3`/`hvac`); see Task 3 of the audit
remediation plan.

### Broker selection at startup

`src/connectors/__init__.py` selects the broker based on env
vars in this order of precedence:

1. Paper simulator (`TRA_PAPER_TRADING=true`)
2. Kite (TRA_KITE_*)
3. Angel (TRA_ANGEL_*)
4. Groww (TRA_GROWW_*)
5. **My new broker**: add a clause like
   ```python
   if os.environ.get("TRA_MYBROKER_API_KEY"):
       return MyBrokerBroker(...)
   ```
6. Raise `RuntimeError` if none of the above match.

> **Do not enable live broker routing without passing
> [`live_trading_gate.md`](live_trading_gate.md).** The 5-day
> paper run is the gate; do not skip it.

### Tests

For each broker module, write a `tests/test_my_broker.py` that
mocks the HTTP layer (`httpx_mock` or `respx`). The paper run
should never depend on a live broker; tests should pass
without network access.

---

## 7. Add an agent

Agents live in `src/agents/`. They are long-running async tasks
that subscribe to typed events, mutate their own state, and
emit new events.

### Base class

`src/agents/base.py` defines `Agent` (abstract) and
`BaseAgent` (concrete). The four methods you must implement
in your subclass are:

```python
class BaseAgent(Agent):
    def __init__(self, name, log_level=None, event_store=None):
        # sets self.name, self.status, self.event_store, ...
        # subclasses call super().__init__() then set up state

    async def on_start(self) -> None:    # called once at start
        # subscribe to event types, start background tasks
        ...

    async def on_stop(self) -> None:     # called once at shutdown
        # cancel background tasks, flush state
        ...

    async def on_event(self, event: Event) -> None:
        # hot path: called for every subscribed event type
        ...

    async def health(self) -> dict[str, Any]:
        # return dict like {"status": "ok", "queue_depth": 0, ...}
        ...
```

`BaseAgent` also gives you:
- `self.event_store` — a `create_event_store()` instance (reads
  `TRA_EVENT_STORE_TYPE`)
- `subscribe(EventType.SIGNAL)` / `publish(event)` helpers
- Heartbeat emission every 10 s (configurable via
  `_health_emit_interval_seconds`)
- Graceful-shutdown handling (cancels `self._tasks`)

### Minimal example

```python
# src/agents/my_new_agent.py
import asyncio
import logging
from src.agents.base import BaseAgent
from src.schemas.events import Event, EventType

logger = logging.getLogger(__name__)


class MyNewAgent(BaseAgent):
    def __init__(self, poll_interval_seconds: float = 5.0) -> None:
        super().__init__(name="my_new_agent")
        self._poll_interval = poll_interval_seconds
        self._counter = 0

    async def on_start(self) -> None:
        self.subscribe(EventType.OHLCV)
        self._tasks.append(asyncio.create_task(self._poll_loop()))
        logger.info("MyNewAgent started; poll=%.1fs", self._poll_interval)

    async def on_stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        logger.info("MyNewAgent stopped")

    async def on_event(self, event: Event) -> None:
        # called for every OHLCV event
        if event.event_type == EventType.OHLCV:
            self._counter += 1

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            # ... background work ...

    async def health(self) -> dict:
        return {
            "status": "ok" if self.status == "running" else "degraded",
            "ohlcv_seen": self._counter,
            "poll_interval": self._poll_interval,
        }
```

### Wiring

1. Add the import + factory in `src/agents/__init__.py`.
2. Add the agent to `src/system.py`'s `TradingSystem` startup:
   ```python
   self.my_new_agent = MyNewAgent(poll_interval_seconds=5.0)
   self.agents.append(self.my_new_agent)
   ```
3. Add a health endpoint mapping in `dashboard/server.py` if
   the agent should appear in the React dashboard.
4. Write a test in `tests/test_my_new_agent.py`:
   - Use an in-memory event store (`TRA_EVENT_STORE_TYPE=memory`):
     ```python
     import os
     os.environ["TRA_EVENT_STORE_TYPE"] = "memory"
     ```
   - Verify `on_start` → `on_event` → `on_stop` lifecycle.
   - Verify `health()` returns the expected shape.

### What NOT to do in agent code

- Do **not** block the event loop. No `time.sleep`, no
  synchronous DB calls.
- Do **not** mutate shared state across agents. Communicate
  via events only.
- Do **not** import from `dashboard/`. Agents run in the
  TradingSystem process; the dashboard runs in a separate
  FastAPI app.
- Do **not** use the `__new__` singleton pattern (see
  `KillSwitch`). Use a module-level factory function or DI.

---

## 8. First PR checklist

Use this before opening your first pull request. Each item is
*expected* to be true for a clean PR; deviations must be
called out in the PR description.

### Code quality

- [ ] `make test` passes locally with **≥ 80 % coverage** for any
      new module. New tests added for each new public function.
- [ ] `ruff check src/` reports zero issues for files you
      touched.
- [ ] `mypy src/` reports zero new issues (pre-existing 12-code
      disables are tracked in Wave 5 Task 28).
- [ ] No new `print()` calls in `src/`. Use `logger`.

### Style + conventions

- [ ] Public functions have type hints (parameters + return).
- [ ] Pydantic v2 models used for any new event types; added
      to `src/schemas/events.py` and exported in
      `src/schemas/__init__.py`.
- [ ] No new third-party deps added to `pyproject.toml`
      without justification in the PR body. If adding, use
      an `extras` entry (e.g., `[my_extra]`) so the dep is
      opt-in.
- [ ] Module docstring present for new files; explains *what*
      and *why* (not *how*).

### Security

- [ ] No secrets in code or tests. Run
      `./scripts/verify_no_secrets.ps1` (or `.sh`) before
      committing.
- [ ] Pre-commit hook installed: `git config core.hooksPath .githooks`.
- [ ] No new direct broker-credential handling — use
      `src/utils/vault.py` `get_secret()`.
- [ ] If you touched an HTTP control endpoint, verified
      `TRA_HTTP_AUTH_TOKEN` is enforced (see
      `dashboard/server.py:26`).

### Documentation

- [ ] If you added a strategy: updated
      [`active_strategy_set.md`](active_strategy_set.md) with
      weight + cold-start.
- [ ] If you added a connector: added a row to the "Broker
      connectors" table in [`ARCHITECTURE.md`](ARCHITECTURE.md).
- [ ] If you added an agent: added a row to the "Agents"
      table in [`ARCHITECTURE.md`](ARCHITECTURE.md).
- [ ] If the change is user-visible: added a row under
      `[Unreleased]` in [`CHANGELOG.md`](../CHANGELOG.md) with
      the commit hash.
- [ ] If the change affects operations: added a section to
      [`RUNBOOK.md`](RUNBOOK.md) (Symptom → Diagnosis → Action).

### Git hygiene

- [ ] Branched from `master`, descriptive name
      (`feat/...`, `fix/...`, `chore/...`).
- [ ] One logical change per commit; commit messages are
      imperative + explain the *why*.
- [ ] `git log master..HEAD` reads as a coherent story
      (squash noisy fixups locally).
- [ ] **Do not push `--force` to `master`.** If your branch
      needs a force-push (e.g., after rebase), it is your
      branch only.

### PR body

- [ ] Title matches the commit subject
- [ ] "What" and "Why" in the first paragraph
- [ ] "How to verify" — exact commands an ops engineer can
      run to reproduce your test
- [ ] "Risks" — what could go wrong; rollback plan
- [ ] Linked issues / plan tasks (e.g., "Closes audit
      remediation Task 35")
- [ ] Screenshots / traces for any UI / dashboard change

---

## Where to ask for help

- **Architecture questions**: read [`ARCHITECTURE.md`](ARCHITECTURE.md)
  first, then ask in the team channel.
- **Operational questions** (something on fire): see
  [`RUNBOOK.md`](RUNBOOK.md), Section 1 (kill switch) and
  Section 4 (stuck reconciliation) cover 90 % of incidents.
- **Strategy tuning questions**: see
  [`active_strategy_set.md`](active_strategy_set.md) and
  [`strategy_menu.md`](strategy_menu.md) for what's been tried.
- **Pre-burn-in or pre-live questions**: see
  [`live_trading_gate.md`](live_trading_gate.md) for the
  promotion criteria.
