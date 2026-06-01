# Trading System — Master Plan
> Code-first audit · June 2026 · Evidence-based, not aspirational

---

## What the System Actually Is

Event-driven, multi-agent trading system targeting NSE equities (India).
Currently paper-only via SQLite event bus. Kite/Zerodha is the only wired live broker.

**Confirmed working components:**
- Async event bus (SQLite / Kafka / Postgres / in-memory backends)
- MarketIntelAgent — tick + OHLCV ingestion, multi-timeframe aggregation
- StrategyGenAgent — 8 strategies, consensus voting, trailing SL/TP
- RiskManagementAgent — 6 pre-trade checks, market hours, square-off window
- ExecutionAgent — pending-signal queue, risk-gated execution, TWAP slicing
- KillSwitch — daily loss %, drawdown %, auto-reset, position cleanup
- PositionRegistry — singleton, thread-safe, SL/TP/trailing stop
- TransactionCostModel — STT, GST, brokerage, SEBI fees, slippage
- BacktestEngine — tick replay, cost model, equity curve, Sharpe ratio
- RegimeDetectionAgent — ADX/ATR-based trending/mean-reverting/vol regime
- PerformanceDecayDetector — rolling Sharpe per strategy, auto-disable
- ReflectionEngineAgent — LLM-guided strategy mutation via Gemini
- KiteBroker — Zerodha Kite Connect order placement

**Data providers (market data only, no order execution):**
- Angel One, Groww, Jugaad (fallback), Yahoo Finance

---

## Scores (post-audit)

| Dimension | Score | Reason |
|---|---|---|
| Code Quality | 5 / 10 | Solid architecture, 4 critical bugs |
| Reliability | 4 / 10 | No reconciliation, async race conditions |
| Profitability Potential | 2 / 10 | Zero-edge strategies, low consensus threshold |
| Risk Control | 5 / 10 | Well-designed but buggy kill-switch reset |
| Scalability | 5 / 10 | Overengineered in places, under-built in others |
| Live-Money Ready | 2 / 10 | No. See critical bugs below. |

---

## Critical Bugs (fix before any real money)

### BUG-1 — KillSwitch async race condition
**File:** `src/risk/kill_switch.py`
**Problem:** `check_limits()` is `async def` but uses no asyncio lock. Two concurrent
signals can both pass the daily-loss check before the first `trigger()` coroutine completes.
**Fix:** Add `asyncio.Lock` acquired at the top of `check_limits`.

```python
# Add to __new__:
cls._instance._lock = asyncio.Lock()

# Wrap check_limits body:
async with self._lock:
    if self._active:
        return True
    ...
```

---

### BUG-2 — Risk-check correlation fallback is unsafe
**File:** `src/agents/execution.py` → `_handle_risk_check()`
**Problem:** If `_signal_event_id` is missing, execution falls back to matching by
`instrument + direction` — the first match in the pending dict. Two concurrent signals
for the same instrument in opposite directions will cross-wire orders.
**Fix:** Make `_signal_event_id` mandatory. Reject any RISK_CHECK event that lacks it.
Log and drop rather than guess.

---

### BUG-3 — SQLite order writes have no asyncio lock
**File:** `src/agents/execution.py` → `_persist_order`, `_update_order_status`, `_persist_fill`
**Problem:** `check_same_thread=False` is set but multiple asyncio tasks (TWAP loop +
main execution + shutdown handler) call these methods concurrently. Under load this
corrupts the order log.
**Fix:** Add `asyncio.Lock` as `self._db_lock` in `__init__`, acquire it in all three
persistence methods.

---

### BUG-4 — Kill-switch HTTP reset does not re-enable strategy generator
**File:** `src/main.py` → `_handle_metrics_request` (path `/api/kill-switch/reset`)
**Problem:** `KillSwitch().reset()` is called with no `system` argument. The kill-switch
flag clears but `strategy_gen._running` stays `False`. The system silently stops generating
signals after a manual reset.
**Fix:** Pass the live `system` reference into the HTTP handler.

```python
# Store system on the handler closure:
elif path == "/api/kill-switch/reset" and request_line.startswith("POST"):
    KillSwitch().reset(system=system)  # system captured from main()
```

---

## High-Priority Code Bugs

### BUG-5 — RSI uses simple MA, not Wilder's EMA
**File:** `src/strategies/technical.py` → `RSIStrategy.evaluate()`
All RSI backtest results are wrong. Standard RSI requires Wilder's smoothed moving average.

```python
# Replace avg_gain/avg_loss simple mean with Wilder's smoothing:
# First period: simple average (same as now)
# Subsequent: avg_gain = (prev_avg_gain * (window-1) + current_gain) / window
```

### BUG-6 — Ichimoku midpoint uses closes, not high/low
**File:** `src/strategies/technical.py` → `IchimokuStrategy._midpoint()`
Ichimoku conversion and base lines are defined as `(highest_high + lowest_low) / 2`.
Using closes produces wrong cloud levels in any volatile session.
**Fix:** Pass `highs` and `lows` lists into `_midpoint` and use `max(highs[-period:])` and
`min(lows[-period:])`.

### BUG-7 — Backtest uses synthetic timestamps by default
**File:** `src/backtest/engine.py`
Ticks without a `timestamp` field get sequential 1-second timestamps from a hardcoded
base date. Market-hours filters and time-sensitive strategies are meaningless on this data.
**Fix:** Raise `ValueError` if tick data has no timestamp. Do not silently fabricate time.

### BUG-8 — DecayDetector calls asyncio.create_task from synchronous method
**File:** `src/monitoring/decay_detector.py` → `_disable_strategy()`
Crashes with `RuntimeError: no running event loop` outside an async context.
The decay event is silently lost.
**Fix:** Accept an `asyncio.AbstractEventLoop` or use `asyncio.get_event_loop().call_soon_threadsafe`.

### BUG-9 — Python 3.14 alpha bytecache present
`.pyc` files under `cpython-314` detected in `__pycache__` dirs.
Running an alpha interpreter in production is unacceptable.
**Fix:** Pin `python_requires = ">=3.12,<3.13"` in `pyproject.toml`. Delete all 3.14 cache.

### BUG-10 — Duplicate order_state.db
`order_state.db` exists in both project root and `state/order_state.db`.
Old code wrote to the wrong path. Historical orders may be split across both files.
**Fix:** Delete root copy. Add to `.gitignore`. Verify `_ORDER_DB_PATH` points to `state/`.

---

## Trading Diagnosis

### Why this will not make money yet

**T1 — No proven edge. All 8 strategies are standard lagging indicators.**
SMA crossover, RSI, Bollinger Bands, MACD, ATR breakout, Ichimoku, Volume, Mean reversion.
Every one is in every free trading tutorial. They are extensively arbitraged on liquid NSE
large-caps. Consensus voting over zero-edge components produces zero-edge consensus.

**T2 — Consensus threshold of 0.4 is too low.**
A single moderate-confidence vote from a 0.5-weight strategy fires a live order.
The 120s cooldown exists to patch a signal flood that better threshold design would prevent.
**Immediate fix: raise to 0.65–0.70.**

**T3 — Paper fill assumes instant fill at last tick + 5bps.**
Real MIS market orders on ₹50k fills in mid-cap NSE: 15–40bps slippage.
Paper results overstate live performance by a factor of 2–5x in costs alone.

**T4 — Fixed 1% risk / 2× ATR sizing ignores edge confidence.**
In high-vol regimes ATR is huge → quantity = 1. In low-vol ATR is tiny → quantity blows up.
No relationship between position size and actual signal quality.

**T5 — All strategies hardcoded to "minute" timeframe.**
No multi-timeframe confirmation. A 1-min MACD that contradicts the 15-min trend is noise.

**T6 — MIS only — no positional / swing capability.**
Every order is squared off at 15:30. The system cannot hold overnight.
This eliminates ~60% of potentially profitable setups in NSE equities.

**T7 — ReflectionEngine can mutate live strategy.yaml with no backtest gate.**
A Gemini hallucination setting `threshold: 0.001` causes an order flood.
Disable ReflectionEngine in live mode until BUG backtest-gate is implemented.

**T8 — Regime detection only emits on regime change.**
After a restart, StrategyGenAgent defaults to "mean_reverting" weights regardless of
actual market conditions — until the next regime flip occurs.

---

## What's Missing

### Risk / Capital
- No sector / correlation exposure caps
- No portfolio-level VaR (only per-instrument)
- No Kelly criterion or fractional Kelly sizing
- No max open positions limit enforced
- No intraday P&L real-time comparison vs daily kill-switch limit
- No margin utilization check before placing order

### Execution
- No broker position reconciliation on startup
- No partial fill handling in live mode
- No order amendment on stale limit prices
- No execution quality measurement (actual vs expected fill price)
- TWAP interval hardcoded at 30s — not market-adaptive

### Strategy / Edge
- No order flow or market microstructure signals
- No earnings / corporate action calendar filter
- No walk-forward validation gate before strategy promotion to live
- stat_arb.py exists in codebase but is never wired into StrategyGenAgent

### Operations
- No heartbeat / watchdog detecting hung agents
- No automatic circuit breaker on repeated broker API errors
- No secret rotation (Kite access tokens hardcoded in .env)
- No log aggregation (Loki / CloudWatch / Datadog)
- prometheus.yml exists but has no alert rules

### Data Quality
- No tick validation (stale price, zero price, gap detection)
- No corporate actions adjustment (splits, bonuses)
- No bad candle filter (zero volume, extreme OHLCV)
- No audit trail linking fill → order → signal → strategy

---

## Files to Delete

```
src/execution/router.py          # Deprecated, self-documented as unused, emits warning
.playwright-mcp/                 # 33 browser session logs committed to repo
order_state.db                   # Root copy, stale, duplicate of state/order_state.db
dash_stderr.txt                  # Console output committed
dash_stdout.txt                  # Console output committed
graphify-out/                    # Cache directory committed
.tmp/                            # Temp directory committed
trading-system/.opencode         # AI assistant session metadata
```

**Add to .gitignore:**
```
*.db
*.db-shm
*.db-wal
dash_stdout.txt
dash_stderr.txt
.tmp/
graphify-out/
.playwright-mcp/
__pycache__/
*.pyc
```

---

## Files to Simplify

| File / Module | Problem | Action |
|---|---|---|
| `src/agents/personas.py` | ExpertPersonasAgent polls alternative data every 3600s, no evidence of intraday trading value | Remove or disable |
| `src/monitoring/dashboard.py` + `dashboard/` + `monitoring/http_dashboard.py` | Three dashboard implementations | Pick one (HTTP is simplest), delete others |
| `src/event_store/kafka.py` + `postgres.py` | Overengineered for single-process system | Keep SQLite until 10k+ events/sec needed |
| `src/agentic/tasks.py` | Experimental agentic loop, unclear purpose | Document or delete |
| `src/backtest/walk_forward.py` | Valid idea but runs on un-timestamped data (BUG-7) | Fix BUG-7 first, then re-enable |

---

## Rebuild Plan

### Phase 1 — Survival (1–2 weeks)
*Goal: system is safe to run with real money structurally. Still paper-only.*

- [ ] Delete all files in "Files to Delete" section
- [ ] Fix BUG-1: asyncio.Lock on KillSwitch.check_limits
- [ ] Fix BUG-2: Reject RISK_CHECK events without signal_event_id
- [ ] Fix BUG-3: asyncio.Lock on SQLite order writes
- [ ] Fix BUG-4: Pass system ref to kill-switch HTTP reset
- [ ] Fix BUG-5: Wilder's EMA in RSIStrategy
- [ ] Fix BUG-6: high/low midpoint in IchimokuStrategy
- [ ] Fix BUG-7: Raise ValueError on untimstamped backtest data
- [ ] Fix BUG-8: DecayDetector async task creation
- [ ] Fix BUG-9: Pin Python 3.12, delete 3.14 bytecache
- [ ] Fix BUG-10: Remove duplicate order_state.db
- [ ] Raise consensus threshold from 0.4 → 0.65 in settings
- [ ] Add regime broadcast on RegimeDetectionAgent.on_start
- [ ] Disable ReflectionEngine mutations in live mode (env flag)
- [ ] Update .gitignore

**Gate:** All existing tests pass. Paper system runs 5 days without crash.

---

### Phase 2 — Profitability (1–2 months)
*Goal: real edge, real cost model, real reconciliation. Paper Sharpe > 0.8.*

- [ ] Implement broker reconciliation on startup (compare DB vs Kite open orders)
- [ ] Add mandatory backtest gate before ReflectionEngine mutations apply
- [ ] Add multi-timeframe confirmation: minute signal + 15-min trend alignment required
- [ ] Replace 5bps flat slippage with depth-weighted order book model
- [ ] Add earnings calendar filter (block new entries on result day ± 1 session)
- [ ] Add correlation filter: block new signal if portfolio correlation > 0.7 with existing
- [ ] Wire `src/strategies/stat_arb.py` into StrategyGenAgent with proper pair selection
- [ ] Implement full audit trail: fill → order → signal → strategy linkage
- [ ] Add asyncio.Lock around all PositionRegistry writes (currently thread-lock only)
- [ ] Add max open positions cap to RiskManagementAgent settings
- [ ] Build timestamped historical data pipeline (not synthetic)

**Gate:** 30-day paper run. Sharpe > 0.8, max drawdown < 8%, win rate > 48%.
Do not proceed to Phase 3 if gate fails — replace strategies first.

---

### Phase 3 — Institutional grade (3–6 months)
*Goal: live capital. Measurable, observable, recoverable.*

- [ ] Replace or augment lagging indicator ensemble with at least one of:
  - Microstructure signal (order flow imbalance, bid/ask pressure)
  - Validated stat-arb pair with cointegration test + entry/exit z-score
  - ML model with strict walk-forward validation (no lookahead)
- [ ] Full order book integration (Zerodha WebSocket depth feed)
- [ ] Kelly / fractional Kelly position sizing replacing fixed 1% rule
- [ ] Prometheus alert rules: KillSwitch trigger, agent down, broker disconnect, P&L breach
- [ ] PagerDuty / Telegram on-call for critical alerts
- [ ] Secret vault for Kite token rotation (HashiCorp Vault or AWS Secrets Manager)
- [ ] Migrate event store to Postgres for concurrent readers + replay durability
- [ ] CNC / NRML product type support for overnight and swing setups
- [ ] SEBI algo trading registration compliance review
- [ ] P&L attribution per strategy per day for tax reporting

**Gate:** 30-day live run with ≤ ₹10,000 capital. Real slippage matches model within 2×.
Scale up only after gate passes.

---

## Key Configuration Reference

```env
# Consensus — raise immediately
TRA_CONSENSUS_THRESHOLD=0.65
TRA_CONSENSUS_SHORT_THRESHOLD=0.70

# Signal cooldown — keep at 2 minutes minimum
TRA_SIGNAL_COOLDOWN_SECONDS=120

# Kill switch — conservative for Phase 1-2
TRA_KILL_SWITCH_DAILY_LOSS_PCT=0.01
TRA_KILL_SWITCH_MAX_DRAWDOWN_PCT=0.05

# Disable LLM mutation until Phase 2 gate is added
TRA_REFLECTION_MUTATION_ENABLED=false

# Risk limits
TRA_RISK_MAX_POSITION_SIZE=100000
TRA_RISK_MAX_ORDER_VALUE=50000
TRA_RISK_PER_TRADE_LOSS_CAP_PCT=0.01
```

---

## Final Verdict

> **Can this codebase realistically trade live profitably right now? No.**

Not because it is poorly written. The event bus, agent separation, kill switch, position
registry, and cost model show genuine engineering effort — more coherent than most
hobby trading systems.

The problem is that **infrastructure is not edge**.

The 8 strategies are textbook lagging indicators. After ₹20 flat brokerage + STT + 15–40bps
real slippage on NSE mid-cap orders, a strategy needs ~60% win rate at 1:1 RR to break even.
Standard RSI and MA crossovers on minute bars of RELIANCE/TCS do not produce that.

**The path forward is three steps:**
1. Fix the 12 bugs above (1–2 weeks)
2. Run 30 days of corrected paper (threshold 0.65, Wilder's RSI, timestamped data)
3. If paper Sharpe < 0.8 → replace strategies before touching live capital

No amount of architecture improvement fixes a zero-edge signal generator.
