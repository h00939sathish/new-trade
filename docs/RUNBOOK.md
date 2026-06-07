# Operator Runbook

> **Audience**: operators running the paper burn-in, the eventual
> live-trading pilot, and on-call engineers responding to alerts.
> Format: each section follows **Symptom → Diagnosis → Action**.
> This is a *procedures* document; for architecture see
> [`ARCHITECTURE.md`](ARCHITECTURE.md), for promotion criteria see
> [`live_trading_gate.md`](live_trading_gate.md), for deployment see
> [`OPERATIONS.md`](OPERATIONS.md).

---

## Table of contents

1. [Kill switch fires mid-session (e.g., 2 PM)](#1-kill-switch-fires-mid-session)
2. [Add a new instrument to the watchlist](#2-add-a-new-instrument-to-the-watchlist)
3. [Rotate Kite access token (with restart)](#3-rotate-kite-access-token)
4. [Recover from a stuck reconciliation](#4-recover-from-a-stuck-reconciliation)
5. [`state/angel_symbols.json` is missing or corrupt](#5-angel_symbolsjson-is-missing-or-corrupt)
6. [A paper trade didn't fire when expected](#6-a-paper-trade-didnt-fire-when-expected)
7. [Read `logs/runtime_traces/`](#7-read-logsruntime_traces)
8. [Interpret `state/burnin/reconciliation.jsonl`](#8-interpret-stateburninreconciliationjsonl)

---

## 1. Kill switch fires mid-session

**Symptom**:
- `AlertAgent` sends a Telegram: `Kill switch TRIGGERED: <reason>`
- `GET /api/agents/health` shows `RiskManagementAgent.status=kill_switch_active`
- `StrategyGenAgent` stops emitting new `Signal` events (visible in
  the dashboard)
- No new `Order` events in the event store after the trigger time

**Diagnosis**:
The kill switch (`src/risk/kill_switch.py`) is a singleton that
trips on one of:
- **Daily loss ≥ `_max_daily_loss`** (default 5 % of initial capital;
  the default `_max_daily_loss = 5000.0` is overridden by
  `setup()` based on env)
- **Drawdown ≥ `_max_drawdown_pct`** (default 5 %)
- **Manual trip** via dashboard `POST /api/control/kill-switch/active`
  or Telegram command (if wired)

Check `state/burnin/reconciliation.jsonl` (most recent entries) for
the `kill_switch_triggered` event and the `reason` field.

**Action** (in order):
1. **Verify the trigger is real** — the kill switch is *not* a
   flapping mechanism; once tripped, it stays tripped until
   manually reset or until `daily_auto_reset` runs at the next
   session boundary (only if `_auto_reset=True`, the default).
   Confirm via:
   ```bash
   curl -sS -H "Authorization: Bearer $TRA_HTTP_AUTH_TOKEN" \
        http://localhost:8080/api/control/kill-switch/status
   ```
2. **Decide whether to keep trading today**. If the trigger was
   a fat-finger, real PnL drawdown, or regime break, you may
   want to leave it tripped and review tomorrow. If it was a
   false positive (data glitch, misconfigured daily-loss %), do
   not reset without understanding why.
3. **Manual reset (only if justified)**:
   ```bash
   curl -X POST -H "Authorization: Bearer $TRA_HTTP_AUTH_TOKEN" \
        http://localhost:8080/api/control/kill-switch/reset
   ```
   This calls `KillSwitch.reset(system)` which sets
   `_active = False` and re-enables `StrategyGenAgent` via
   `system.strategy_gen._running = True`.
4. **Document the incident** in `state/burnin/incidents/`
   (create the dir if needed). Note: trigger time, reason,
   capital at trigger, decision to reset or hold, operator
   initials, root-cause hypothesis.

> **Do not** reset the kill switch more than once per day
> without a written post-mortem; that is a flapping pattern.

---

## 2. Add a new instrument to the watchlist

**Symptom**:
- StrategyGenAgent is not generating signals for an instrument you
  expect to be active
- `/api/portfolio` does not show the symbol
- `state/angel_symbols.json` does not contain the symbol (or the
  config in `TRA_WATCHLIST` does not)

**Diagnosis**:
The watchlist is set by the `TRA_WATCHLIST` env var (comma-separated
NSE symbols, default `RELIANCE,TCS,INFY,HDFCBANK` per
`docker-compose.yml`). Adding an instrument requires (a) updating
the env var and (b) ensuring the symbol exists in the symbol
universe (Yahoo for backtest, Angel for live).

**Action**:
1. **Local paper / dev**:
   ```bash
   # Edit .env
   TRA_WATCHLIST=RELIANCE,TCS,INFY,HDFCBANK,<NEW_SYMBOL>
   ```
2. **Compose / Railway**: edit `docker-compose.yml` line 71 (or the
   `TRA_WATCHLIST` Railway env var), then redeploy:
   ```bash
   docker compose up -d trading-app   # local
   # Railway: git push triggers redeploy
   ```
3. **Verify the symbol resolves**:
   ```bash
   python -c "from src.connectors.yahoo import YahooProvider; \
   print(YahooProvider().lookup('<NEW_SYMBOL>'))"
   ```
   If `None` is returned, the symbol is not in Yahoo's universe —
   try the NSE-format symbol (e.g., `RELIANCE.NS` for backtest)
   or use the Angel connector for live.
4. **Confirm at next session open** (9:15 IST) that
   `MarketIntelAgent` emits `OHLCV` events for the new symbol.
   The cold-start math (see
   [`active_strategy_set.md`](active_strategy_set.md)) means
   signals won't fire until ~12:35 IST because of the 200-candle
   EMA200 filter.
5. **For backtests only**: pass the symbol directly to
   `scripts/run_system_backtest.py --symbols <NEW_SYMBOL>`.

> **Do not** add symbols while the burn-in is in its 5-day
> window; the burn-in gate is for *baseline* performance with
> the existing watchlist. Add symbols only at session end.

---

## 3. Rotate Kite access token

**Symptom**:
- `KiteBroker` raises `TokenException` or `InputException` on order
  placement
- `KiteMarketDataProvider` returns stale ticks or 401 errors
- Alert: `Broker API auth failed: kite`

**Diagnosis**:
Kite access tokens expire at **6:00 AM IST every day** (Zerodha
policy). Tokens are persisted to `state/kite_token.json` and
loaded at startup. The token is also in the running process
memory; a restart is required to pick up a new token.

**Action**:
1. **Generate a fresh request token** by completing the Kite login
   flow in a browser (manual step — cannot be automated). The
   request token is a one-time token from the redirect URL.
2. **Exchange request token for access token**:
   ```bash
   python -m src.auth.kite_session --request-token <TOKEN> \
          --api-key $TRA_KITE_API_KEY \
          --api-secret $TRA_KITE_API_SECRET
   ```
   This writes `state/kite_token.json` with the new access token
   and expiry.
3. **Restart the trading system** to pick up the new token:
   ```bash
   # Stop the burn-in
   ./scripts/stop_paper_burnin.ps1
   # Start it again
   ./scripts/start_paper_burnin.ps1
   ```
   (For Railway: redeploy the service.)
4. **Verify**:
   ```bash
   curl -sS -H "Authorization: Bearer $TRA_HTTP_AUTH_TOKEN" \
        http://localhost:8080/api/agents/health | jq '.kite.connected'
   ```
   Should return `true` within 30 s of restart.
5. **Schedule the rotation**: the token will expire again in ~24 h.
   Add a calendar reminder or wire a daily cron for step 1-3.
   (An automated refresh-token flow is planned in a future wave
   — see `.omo/plans/complete-audit-remediation.md` Wave 8.)

> **Do not** commit `state/kite_token.json` or any request/access
> token to git. The `k1bpotx2f133yrms` leak documented in
> [`SECURITY.md`](../SECURITY.md) is the cautionary tale.

---

## 4. Recover from a stuck reconciliation

**Symptom**:
- `ReconciliationAgent` heartbeat shows `last_reconciliation_age > 600s`
- Dashboard `Reconciliation` tab shows yellow/red status
- `state/burnin/reconciliation.jsonl` last entry is more than 10 min
  old
- Orders are being placed by `ExecutionAgent` but `Fill` events are
  not appearing in the event store

**Diagnosis**:
`ReconciliationAgent` is supposed to cross-check internal positions
vs broker positions every 60 s (configurable). A *stuck* agent
usually means one of:
- **Broker API timeout** (Kite is rate-limited; Angel/Groww less so)
- **Async task swallowed an exception** (look for traceback in
  `state/burnin/stderr.log`)
- **Database lock** — `state/order_state.db` is in WAL mode but
  long-running readers can block writers

**Action**:
1. **Check the agent heartbeat first**:
   ```bash
   ./scripts/check_paper_burnin.ps1
   ```
   Look at the `recent_errors` field. Common culprits:
   - `asyncpg.exceptions.ConnectionDoesNotExistError` — Postgres
     connection lost; check Railway Postgres status
   - `sqlite3.OperationalError: database is locked` — kill long
     `sqlite3` CLI sessions and restart
   - `kiteconnect.exceptions.NetworkException` — Kite API down;
     wait and retry
2. **Inspect the agent's last log line**:
   ```bash
   tail -n 200 state/burnin/stderr.log | grep -A 20 reconciliation
   ```
3. **If the agent is wedged** (no progress for 5+ min, no recent
   errors), restart the system:
   ```bash
   ./scripts/stop_paper_burnin.ps1
   ./scripts/start_paper_burnin.ps1
   ```
   The new process will rebuild reconciliation state from the
   event log (the `Fill` events are durable).
4. **If broker reconciliation is missing fills** (a real bug, not
   a stuck agent): use the `ReconciliationAgent`'s dry-run mode
   to surface the diff:
   ```bash
   python -m src.agents.reconciliation --dry-run
   ```
   The dry-run will list broker-reported fills vs internal fills
   without mutating state.
5. **Post-recovery**: write a one-line incident note in
   `state/burnin/incidents/<date>-reconciliation-stuck.md` so the
   5-day burn-in log captures the recovery.

> **Do not** delete `state/order_state.db` or
> `state/trading_events.db` during recovery; both are the audit
> trail. If you suspect DB corruption, see Section 5 (the
> `angel_symbols.json` procedure generalizes to any state file).

---

## 5. `state/angel_symbols.json` is missing or corrupt

**Symptom**:
- `AngelMarketDataProvider.lookup()` returns `None` for every symbol
- Alert: `Angel symbol index unavailable; falling back to static list`
- `state/angel_symbols.json` is missing, zero-bytes, or fails JSON
  parse

**Diagnosis**:
`state/angel_symbols.json` is a **26 MB cache** of the Angel One
NSE symbol universe (instrument master + token map). It is built
on first run by `src/connectors/angel/symbol_index.py` and
persisted to `state/`. A corrupt file usually means:
- Process killed mid-write (no atomic rename)
- Disk full
- Manual `git checkout` of an old state file (it is in
  `.gitignore` so this should not happen, but check anyway)

**Action**:
1. **Verify the file**:
   ```bash
   python -c "import json; print(len(json.load(open('state/angel_symbols.json'))))"
   ```
   If the parse fails, the file is corrupt. If the count is
   unreasonably small (< 1000), it is stale.
2. **Move the corrupt file aside** (do NOT delete — see the
   warning below):
   ```bash
   mv state/angel_symbols.json state/angel_symbols.json.corrupt.$(date +%Y%m%d)
   ```
3. **Rebuild the index**:
   ```bash
   python -c "from src.connectors.angel.symbol_index import AngelSymbolIndex; \
   idx = AngelSymbolIndex(); \
   idx.rebuild()"
   ```
   This pulls the live instrument master from Angel One's
   `https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json`
   and writes a fresh `state/angel_symbols.json`.
4. **Verify the rebuild**:
   ```bash
   python -c "from src.connectors.angel.symbol_index import AngelSymbolIndex; \
   print(len(AngelSymbolIndex()._symbols))"
   ```
   Should return ~10 000–20 000 NSE + BSE instruments.
5. **Restart the system** if it was running in degraded mode:
   ```bash
   ./scripts/stop_paper_burnin.ps1
   ./scripts/start_paper_burnin.ps1
   ```

> **Do not** `rm -rf state/`. That destroys `trading_events.db`
> (35 MB, the full event log), `order_state.db` (1 MB, the order
> state machine), the burn-in state, and any reconciliation
> reports. **All** state files are gitignored but **none** are
> rebuildable from code — the event log is the only source of
> truth for fills and signals.

> **Retention note**: the planned 30-day TTL on
> `state/angel_symbols.json` is Wave 4 Task 26; for now the file
> grows monotonically and is rebuilt manually as above.

---

## 6. A paper trade didn't fire when expected

**Symptom**:
- MarketIntelAgent is emitting `OHLCV` events
- RegimeAgent is broadcasting `RegimeBroadcast`
- But no `Signal` event appears for the symbol/time you expected
- Or: a `Signal` appears, but no `Order` event follows

**Diagnosis** (follow the chain top-down):
1. **No `Signal`?** The `StrategyGenAgent` evaluates the active
   strategy set (`src/config/strategy_config.py`) against the
   `OHLCV` + `RegimeBroadcast`. Possible reasons for silence:
   - **Cold-start**: `ema200_regime_gate` needs 200 candles of
     1-min OHLCV (3.3 h) before its first read. Before 12:35 IST,
     signals are blocked. See
     [`active_strategy_set.md`](active_strategy_set.md) § "Cold-
     start math".
   - **Regime blocks**: `adx_regime_filter` blocks when ADX < 25
     (no trend); `ema200_regime_gate` blocks counter-trend signals.
   - **Consensus below threshold**: consensus threshold is 0.65
     (raised in commit `73008e5`). A single weak strategy vote
     does not pass.
   - **Watchlist mismatch**: the symbol is not in
     `TRA_WATCHLIST` (Section 2).
2. **`Signal` but no `Order`?** The `RiskManagementAgent` vetoed
   the signal. Check the most recent `RiskCheck` event in the
   event store for a `vetoed=true` flag and the reason.
   Common reasons:
   - **Kill switch active** (Section 1)
   - **Position size cap** hit for the symbol or sector
   - **Daily loss limit** close to triggering
   - **No available capital** (all in existing positions)
3. **`Order` but no `Fill`?** The `ExecutionAgent` placed the
   order but the paper simulator never produced a `Fill`. Check
   the `Order` event's `state` field — if it is `SUBMITTED` and
   stays there, the paper fill simulator is wedged.
4. **`Fill` but PnL is wrong?** Check `src/risk/costs.py` —
   slippage + brokerage + STT + GST are applied. A 5 bps flat
   slippage is the current model (Wave 7 Task 45 will make it
   depth-weighted).

**Action**:
1. **Inspect the event log** for the symbol around the expected
   time:
   ```bash
   sqlite3 state/trading_events.db "SELECT event_type, ts, payload \
   FROM events WHERE ts > '2026-06-05 14:00:00' AND json_extract(payload, '$.symbol') = 'RELIANCE' \
   ORDER BY ts LIMIT 50;"
   ```
2. **If cold-start**: wait until 12:35 IST for the EMA200
   filter to warm up; signals will resume automatically.
3. **If risk vetoed**: check the dashboard
   `/api/agents/health` for `RiskManagementAgent.last_veto_reason`
   and `RiskManagementAgent.recent_vetoes`.
4. **If paper fill simulator is wedged**: restart the system
   (Section 4 step 3). Open orders will be reconciled on
   startup from the event log.
5. **If a strategy is misbehaving**: pause it via the dashboard
   `POST /api/control/strategies/<name>/pause` (auth required)
   while you investigate.

> **Do not** edit `src/config/strategy_config.py` weights while
> the burn-in is running. The burn-in is meant to capture
> *baseline* performance; tweaking weights mid-burn-in
> invalidates the gate.

---

## 7. Read `logs/runtime_traces/`

**Symptom**:
- You want to understand what happened in a past session
- You need latency data for a specific order
- You want to reconstruct the event sequence for a specific symbol

**Diagnosis**:
`logs/runtime_traces/` is gitignored. It contains structured
traces from `src/monitoring/latency_tracer.py`. Each file is a
JSON-Lines stream (one event per line).

**Action**:
1. **List the trace files**:
   ```bash
   ls -la logs/runtime_traces/ | tail -n 20
   ```
   Files are named `trace_<ISO-timestamp>.jsonl`. The most recent
   is the most useful.
2. **Read a trace** (human-friendly with `jq`):
   ```bash
   cat logs/runtime_traces/trace_2026-06-05T091500.jsonl | jq -c \
     '{ts, kind, symbol, latency_ms, ok}'
   ```
   Schema (one record per line):
   ```json
   {
     "ts": "2026-06-05T09:15:32.123Z",
     "kind": "order_submit" | "fill" | "signal" | "regime_eval" | ...,
     "symbol": "RELIANCE",
     "latency_ms": 12.7,
     "ok": true,
     "extra": { ... kind-specific fields ... }
   }
   ```
3. **Find slow operations**:
   ```bash
   cat logs/runtime_traces/trace_*.jsonl | \
     jq -c 'select(.latency_ms > 50) | {ts, kind, symbol, latency_ms}'
   ```
4. **Trace a specific order**:
   ```bash
   ORDER_ID="ord_2026_06_05_RELIANCE_abc123"
   grep "$ORDER_ID" logs/runtime_traces/*.jsonl | jq -c .
   ```
5. **Compare to event store** — the trace latency should match
   the time between the corresponding events in
   `state/trading_events.db`:
   ```bash
   sqlite3 state/trading_events.db "SELECT ts, event_type FROM events \
   WHERE json_extract(payload, '\$.client_order_id') = '$ORDER_ID' \
   ORDER BY ts;"
   ```

> **Do not** rely on `runtime_traces/` for *durable* state — it
> is best-effort, in-process, and not replicated. The event
> log (`state/trading_events.db`) is the only durable record.

---

## 8. Interpret `state/burnin/reconciliation.jsonl`

**Symptom**:
- You want to know the reconciliation state for the burn-in
- You want to debug a position drift
- The 5-day burn-in gate evaluation script reads this file

**Diagnosis**:
`state/burnin/reconciliation.jsonl` is a JSON-Lines file
written by the `ReconciliationAgent` (and the burn-in scoring
harness in `src/monitoring/burnin.py`). One record per line;
one record per reconciliation run (default: every 60 s).

**Action**:
1. **List recent records**:
   ```bash
   tail -n 5 state/burnin/reconciliation.jsonl | jq .
   ```
2. **Schema** (one record):
   ```json
   {
     "ts": "2026-06-05T14:30:00.123Z",
     "internal_positions": { "RELIANCE": 100, "TCS": 50, ... },
     "broker_positions":   { "RELIANCE": 100, "TCS": 50, ... },
     "drift":              { "RELIANCE": 0, "TCS": 0, ... },
     "drift_pct":          0.0,
     "ok":                 true,
     "anomalies":          [],
     "session_pnl":        1234.56,
     "cumulative_pnl":     4567.89,
     "kill_switch":        false
   }
   ```
3. **Field meanings**:
   - `internal_positions` — what the local `PortfolioAgent`
     thinks it holds
   - `broker_positions` — what the broker API reports
   - `drift` — `broker_positions - internal_positions` per symbol;
     **must be all zeros** in a healthy system
   - `drift_pct` — total absolute drift as a fraction of total
     position value; alert if `> 0.001` (0.1 %)
   - `ok` — `false` if any anomaly is non-empty
   - `anomalies` — list of strings describing the issue
     (e.g., `"missing_fill: RELIANCE qty=100"`)
   - `session_pnl` — realized + unrealized PnL for the current
     session (resets at session boundary)
   - `cumulative_pnl` — since burn-in start (2026-06-05)
   - `kill_switch` — `true` if active at the time of the
     reconciliation
4. **Investigate drift**:
   ```bash
   tail -n 1 state/burnin/reconciliation.jsonl | \
     jq '.drift | to_entries | map(select(.value != 0))'
   ```
   If any symbol shows non-zero drift:
   - **Single-symbol drift**: usually a missed `Fill` event
     (Section 4)
   - **Multi-symbol drift**: usually a wrong broker selection
     (Section 7 of [`OPERATIONS.md`](OPERATIONS.md) — broker
     selection) or a manual flatten via the dashboard that
     didn't get reconciled
5. **Run the burn-in gate check** (the 5-day paper-run
   promotion test):
   ```bash
   ./scripts/check_paper_burnin.ps1
   ```
   The script reads this file plus `metadata.json` and emits a
   pass/fail per the
   [`live_trading_gate.md`](live_trading_gate.md) criteria.

> **Do not** edit `reconciliation.jsonl` by hand. It is
> append-only from `ReconciliationAgent`. If the file is
> corrupt, move it aside and let the agent create a new one on
> next run (Section 5 procedure generalizes).

---

## Quick reference: scripts

| Script | Purpose | When to run |
|---|---|---|
| `scripts/start_paper_burnin.ps1` | Start the paper burn-in (Windows) | Session open, 9:00 IST |
| `scripts/stop_paper_burnin.ps1` | Stop the paper burn-in (Windows) | Session close, 15:45 IST, or on kill switch |
| `scripts/run_paper_5d.ps1` | Run the 5-day paper burn-in unattended | Once per burn-in cycle |
| `scripts/check_paper_burnin.ps1` | Read burn-in state + emit pass/fail | On-demand, or in a 5-min cron |
| `scripts/replay_events.py` | Replay events from `state/trading_events.db` to a target date | Forensics, debugging |
| `scripts/run_agent.py` | Run a single agent in isolation | Local dev, debugging |
| `scripts/run_system_backtest.py` | Run a system backtest over a date range | After strategy changes |
| `scripts/verify_no_secrets.{ps1,sh}` | Scan repo for committed credentials | Pre-commit hook (planned) |
| `scripts/scrub_credentials.{ps1,sh}` | Local-only credential scrub (does NOT rewrite history) | After a leak (Task 1 follow-up; requires user sign-off for `git filter-branch`) |
| `scripts/run_paper_30d.py` | Run a 30-day paper burn-in (longer soak test) | Post-5-day-gate, before live |
| `scripts/run_validation.py` | Run the validation suite (regime, strategies, costs) | After parameter changes |

## Quick reference: env vars

| Var | Purpose | Default |
|---|---|---|
| `TRA_HTTP_AUTH_TOKEN` | Bearer token for control endpoints | (must be set; WARNING logged if empty) |
| `TRA_PAPER_TRADING` | Force paper mode | `true` during burn-in |
| `TRA_LIVE_TRADING_ENABLED` | Enable live broker routing | `false` until gate passed |
| `TRA_WATCHLIST` | Comma-separated NSE symbols | `RELIANCE,TCS,INFY,HDFCBANK` |
| `TRA_EVENT_STORE_TYPE` | `sqlite` (default) / `postgres` / `kafka` | `sqlite` |
| `TRA_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
| `TRA_REFLECTION_MUTATION_ENABLED` | Allow `ReflectionEngine` to mutate strategy params | `false` (must remain false during burn-in) |
| `MONITOR_BOT_TOKEN` | Telegram bot token for alerts | (must be set) |
| `MONITOR_CHAT_ID` | Telegram chat ID for alerts | (must be set) |
| `MONITOR_API_URL` | Paper-report endpoint URL | `http://localhost:8080/api/paper-report` (dev) |
| `TRA_KITE_API_KEY` / `TRA_KITE_ACCESS_TOKEN` | Zerodha Kite creds | (must be set for live) |
| `TRA_GROWW_API_KEY` / `TRA_GROWW_API_SECRET` / `TRA_GROWW_TOTP_SECRET` | Groww creds | (must be set for live) |
