# Phase 1 Gate — 5-Day Paper Run Launch Checklist

> Goal: Run the system in paper-only mode for 5 consecutive trading days without crashes, with kill-switch proven and reconciliation clean.

---

## Audit findings (from `src/main.py` + `src/system.py` review)

### Paper-only enforcement: **VERIFIED** ✓

Defense chain:
- `main.py:125-130` — Live mode refuses to start without Kite creds
- `system.py:44-51` — `KiteBroker` only instantiated if `live_trading_enabled=True` AND creds present
- `system.py:67-70` — `ExecutionAgent` constructed with `broker=None` in paper mode
- `ExecutionAgent.__init__:100` — `self._paper_trading = broker is None`
- `system.py:137-144` — Post-init guard forces paper trading if broker object present but `live_trading_enabled=False`
- `system.py:146-161` — Kite connection failure in paper mode → falls back to paper; in live mode → raises

### Remaining startup issues (non-blocking but noted)

| # | Issue | Severity | Mitigation |
|---|---|---|---|
| 1 | No positive assertion that `live_trading_enabled=False` for Phase 1 | Low | Wrapper clears Kite creds at startup |
| 2 | `start_paper_burnin.ps1:36` uses watchlist `RELIANCE-EQ,INFY-EQ,HDFCBANK-EQ` but `.env` uses `RELIANCE,HDFCBANK,...` (no `-EQ` suffix) | Medium | New `run_paper_5d.ps1` uses `.env` value verbatim |
| 3 | `start_paper_burnin.ps1:34` sets reconciliation interval to 1800s; `main.py:177` default is 300s with comment saying 1800s is "too sparse" | Low | New wrapper uses 300s |
| 4 | CLI dashboard starts even in non-TTY (could hang in background) | Low | Wrapper sets `TRA_DASHBOARD=0` |
| 5 | No signal handler check for Windows-specific signals | None | `main.py:194-198` catches `NotImplementedError` |

---

## 1. Pre-flight (T-30 min, before market open)

```powershell
# Confirm Python venv and dependencies
& "D:\projects\new trade\.venv\Scripts\python.exe" -c "import src.main; print('OK')"

# Confirm .env is loaded and live trading is OFF
& "D:\projects\new trade\.venv\Scripts\python.exe" -c "from src.config.settings import settings; print(f'live={settings.live_trading_enabled} cons={settings.consensus_threshold}')"
# Expected: live=False cons=0.65

# Confirm Kite creds are NOT in the environment
$env:TRA_KITE_API_KEY=""; $env:TRA_KITE_API_SECRET=""
$env:TRA_KITE_ACCESS_TOKEN=""; $env:TRA_KITE_USER_ID=""
```

Expected output from env check: `live=False cons=0.65`

---

## 2. Env vars (set in wrapper, do not rely on shell)

| Var | Value | Why |
|---|---|---|
| `TRA_KITE_API_KEY` | `""` | Block live broker instantiation |
| `TRA_KITE_API_SECRET` | `""` | Block live broker instantiation |
| `TRA_KITE_ACCESS_TOKEN` | `""` | Block live broker instantiation |
| `TRA_KITE_USER_ID` | `""` | Block live broker instantiation |
| `TRA_LIVE_TRADING_ENABLED` | `false` (default) | Defense-in-depth |
| `TRA_EVENT_STORE_TYPE` | `sqlite` | Default, explicit |
| `TRA_DASHBOARD` | `0` | Suppress CLI dashboard in background |
| `TRA_DASHBOARD_TYPE` | `http` | Metrics-only HTTP server |
| `TRA_METRICS_PORT` | `8080` | Health/metrics endpoint |
| `TRA_BURNIN` | `1` | Enable reconciliation loop |
| `TRA_BURNIN_RECONCILIATION_SECONDS` | `300` | 5-minute reconciliation cadence |
| `TRA_WATCHLIST` | from `.env` | Use Phase 1 watchlist as-is |
| `TRA_CONSENSUS_THRESHOLD` | `0.65` | From Phase 1 config |
| `TRA_REFLECTION_MUTATION_ENABLED` | `false` | Block Gemini mutations in live mode |

---

## 3. Start command

```powershell
# From project root
powershell -ExecutionPolicy Bypass -File scripts\run_paper_5d.ps1
```

The wrapper handles:
- Daily log rotation with `day1.log`, `day2.log`, etc.
- Auto-restart on crash (5s backoff)
- Graceful stop after 5 days
- Final manifest write

---

## 4. What to watch (every hour)

### Health endpoint
```powershell
curl http://localhost:8080/health
```
**Healthy response:** JSON with `market_intel`, `strategy_gen`, `risk_mgmt`, `execution`, etc., all with `running: true` and reasonable queue sizes.

### Metrics endpoint
```powershell
curl http://localhost:8080/metrics
```
Watch for:
- `trading_system_kill_switch_active` — must remain `0`
- `trading_system_open_positions` — non-zero is fine, but not exploding
- `trading_system_events_processed_total` — should increment

### Reconciliation file
```powershell
Get-Content state\burnin\reconciliation.jsonl -Tail 5
```
**Healthy response:** `"status": "ok"`. If `"status": "mismatch"`, investigate `mismatches` field.

### Recent errors
```powershell
Select-String -Path state\burnin\day*.log -Pattern '\] ERROR|Traceback|Exception:' | Select-Object -Last 20
```

---

## 5. Kill-switch smoke test (do this on Day 1 within first hour)

### A. HTTP reset endpoint
```powershell
# Verify endpoint exists (will return 200)
Invoke-WebRequest -Uri "http://localhost:8080/api/kill-switch/reset" -Method POST
```

### B. Manual trigger via debug
Add a one-shot trigger in a Python REPL or test harness:
```python
import asyncio
from src.risk.kill_switch import KillSwitch
from src.system import TradingSystem

async def smoke():
    system = TradingSystem()
    await system.start()
    ks = KillSwitch()
    ks.trigger(reason="smoke test")
    print("Triggered:", ks._active)
    ks.reset(system=system)  # Verify BUG-4 fix
    print("After reset:", ks._active, "strategy_gen running:", system.strategy_gen._running)

asyncio.run(smoke())
```

### C. Daily-loss trigger
Manually push a large synthetic P&L into the kill-switch monitor and confirm the system refuses new orders. Reset before continuing real run.

**Pass criteria:**
- Trigger fires within 1s of breach
- HTTP reset endpoint re-enables strategy_gen (this was BUG-4)
- `system_metrics.kill_switch_active` returns to 0 after reset

---

## 6. Daily review (end of each session)

For each of the 5 days, run:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_paper_burnin.ps1 | Out-File "state\burnin\day${day}_summary.json"
```

Check the summary for:
- `process_running: true` for the full market session
- `health_reachable: true`
- `metrics_reachable: true`
- `reconciliation.status: "ok"` (no drift)
- `recent_errors: []` or only known-benign warnings

---

## 7. Stop conditions (manual kill if any of these occur)

- Crash loop (>3 restarts in 10 minutes) → check `state\burnin\day*_stderr.log`
- `reconciliation.status: "mismatch"` for 2+ consecutive cycles
- `kill_switch_active: 1` for >5 minutes without manual intervention
- Memory leak (`trading_system_open_positions` growing unbounded)
- Any ERROR in stderr.log that mentions `RuntimeError`, `AttributeError`, or `ConnectionError` from broker path

---

## 8. End of run (Day 5 EOD)

The wrapper auto-stops after 5 days and writes:
```
state/burnin/run_manifest.json  — start/end times, crash count, days completed
```

If the wrapper stops early, run:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop_paper_burnin.ps1
```

---

## 9. Gate pass criteria (from `plan.md` Phase 1)

- [x] All 12 bugs fixed
- [x] Phase 1 env vars set in `.env` and `.env.example`
- [ ] **5 trading days completed without crash**
- [ ] Kill-switch smoke test passed on Day 1
- [ ] All daily reconciliations show `"status": "ok"`
- [ ] All daily summaries show `process_running: true` for full session

Once all boxes checked: **Phase 1 gate passes. Begin Phase 2 planning.**
