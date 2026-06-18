# PLAN2 — Delta Audit & Revised Build Plan
> June 16, 2026 · Built from full R&D investigation (Phase 1-6)
> Supersedes gaps in `plan.md` and `docs/remediation_plan_2026-06-02.md`

---

## Part A — Delta: What Both Existing Plans Miss

### A0 — TSMOM Timeframe Mismatch (CRITICAL)
**File:** `src/strategies/tsmom.py` lines 8-14
**Problem:** Uses `short_window=5`, `long_window=20` intended as **days** (60/120/250-day horizons stored in class attrs) but bar feed delivers **1-minute candles**. A 60-period SMA on 1-min data = 1 hour, not 60 days. This means the highest-weighted strategy (40%) silently computes wrong signals.

**Not in plan.md or remediation_plan_2026-06-02.md. Both assume TSMOM works correctly.**

**Fix:** Rename params to `short_hours=1`, `long_hours=4` → convert to `short_window=60`, `long_window=240` for minute bars. Or add bar-to-day aggregation. Verify with known minute-bar test input.

**Gate:** Unit test asserting correct horizon-to-bar conversion.

---

### A1 — Kill Switch State NOT Persisted (HIGH)
**File:** `src/risk/kill_switch.py`
**Problem:** In-memory singleton. State lost on every restart. If the system crashes during a flash crash, kill-switch resets to OFF on restart. System starts taking new positions while market is still collapsing.

**Not in either plan.** plan.md BUG-1/BUG-4 fix async/locking bugs but assume in-memory is fine.

**Fix:** Write kill-switch state to `state/kill_switch.state` on every state change. Read on startup.

**Gate:** SIGKILL while triggered, restart, verify still triggered.

---

### A2 — Paper Fills Are Dangerously Unrealistic (HIGH)
**File:** `src/agents/execution.py` lines 1270-1290
**Problem:** Instant fill at last price with zero slippage. Research shows real MIS market orders on NSE mid-cap have 15-40bps slippage. 30-day paper validation is MEANINGLESS with this model — you'll get a false sense of edge.

**Noted in plan.md T3** ("Paper fill assumes instant fill at last tick + 5bps") but my investigation finds the actual code uses LAST PRICE, not even a 5bps model. The problem is worse than plan.md states.

**Fix:** Volume-aware fill, slippage model (5-20bps stochastic), queue position simulation, partial fills.

**Gate:** Paper win rate degrades 5-15% vs current model. If it doesn't, slippage is still too low.

---

### A3 — Broker Static IP Mandatory (HIGH)
**Evidence:** Zerodha Kite API requires static IP for order placement from April 1, 2025.
**Code:** `src/config/settings.py` references `kite_static_ip` but no validation.
**Problem:** If deployed on Railway (dynamic IP), all order placement requests will be rejected.

**Not in either plan.**

**Fix:** Validate static IP is configured before enabling live mode. Railway deployment needs static egress IP (requires Railway Pro plan or proxy).

---

### A4 — SQLite Will Fail Under Live Tick Volume (HIGH)
**File:** `src/event_store/sqlite.py` — WAL mode, 30s timeout, single writer
**Problem:** At ~1000 events/sec (50 instruments × 20 events/sec during NSE open), SQLite will queue. Write lock causes cascade failures across event bus.

**Noted in plan.md Phase 3** as "Migrate event store to Postgres" — but this is listed as 3-6 month work. It should be TIER 0.

**Fix:** Hot-switch default to Postgres. Keep SQLite fallback for dev.

---

### A5 — EMA200 Cold-Start Eats 53% of Trading Day
**File:** `src/config/strategy_config.py` (EMA200 lookback=200)
**Problem:** First signal possible at 9:15 + 200 min = 12:35 IST. Only 2h55m of a 6h15m session have full signal capability. NSE micro-structure research shows best reversion window is midday (11:30-14:00) — exactly when EMA200 is cold.

**Not in either plan.** plan.md doesn't address cold-start at all.

**Fix:** Reduce EMA lookback to 100 (cold-start 1.7h, signal window 4.6h) or compute on 5-min candles.

---

### A6 — Memory Leak: Unbounded Fill History Dictionary
**File:** `src/agents/execution.py` line 113: `_broker_seen_fills: dict[str, int]`
**Problem:** No eviction. Accumulates all fill IDs indefinitely. Over weeks of running, consumes growing memory.

**Not in either plan.**

**Fix:** LRU eviction (max 10,000 entries) or periodic cleanup of fills older than 7 days.

---

### A7 — No Broker WebSocket Reconnection
**Files:** `src/connectors/kite/client.py`, `src/connectors/kite/market_data.py`
**Problem:** WebSocket disconnection during market hours loses ticks for 5-30s. No exponential backoff, no reconnection logic.

**Not in either plan.**

**Fix:** Exponential backoff reconnection (1s → 2s → 4s → 8s → max 60s). Add `broker_connected` metric.

---

### A8 — Metrics Lost on Restart
**File:** `src/monitoring/metrics.py`, `src/monitoring/metrics_store.py`
**Problem:** Prometheus counters and portfolio gauges are in-memory. Cannot analyze performance across restarts.

**Not in either plan.**

**Fix:** Periodic Prometheus TSDB write or push gateway. SQLite-backed metric snapshot on shutdown.

---

## Part B — Revised TIER Build Plan

### TIER 0 — Live Trading Blockers (BEFORE any real money)
*Goal: System is safe to run with real money. Still paper-only until these are done.*

| # | Item | Effort | Risk | Already in plan.md? |
|---|---|---|---|---|
| P0.1 | Fix TSMOM timeframe mismatch | 2-3h | CRITICAL | ❌ |
| P0.2 | SQLite → Postgres migration | 2-3d | HIGH | Phase 3 only |
| P0.3 | Realistic paper fill model | 1-2d | HIGH | T3 (noted, no fix) |
| P0.4 | Persistent kill switch | 4-6h | HIGH | ❌ |
| P0.5 | Static IP validation for Kite | 1-2h | HIGH | ❌ |
| P0.6 | Broker WebSocket reconnection | 1-2d | HIGH | ❌ |
| P0.7 | Fix `_broker_seen_fills` memory leak | 1-2h | MEDIUM | ❌ |
| P0.8 | EMA200 cold-start config fix | 1-2h | MEDIUM | ❌ |
| P0.9 | Metrics persistence on disk | 6-8h | MEDIUM | ❌ |
| P0.10 | Pre-trade readiness checklist | 2-3h | MEDIUM | Phase 1 (remediation) |

**Not carried over from plan.md (already fixed):** BUG-1 through BUG-10, consensus threshold raise, regime broadcast, ReflectionEngine disable, .gitignore update, file deletion.

---

### TIER 1 — Safety & Reconciliation (1-2 weeks)
*Goal: Every order path has a safety gate. Positions match broker exactly.*

| # | Item | Effort |
|---|---|---|
| P1.1 | Periodic broker reconciliation (every 5 min during market hours) | 1d |
| P1.2 | Partial fill handling in live mode | 2d |
| P1.3 | Circuit breaker on repeated broker API errors | 1d |
| P1.4 | Margin utilization check before order placement | 4h |
| P1.5 | Max open positions cap enforced | 2h |
| P1.6 | Sector/correlation exposure caps | 1d |
| P1.7 | Intraday P&L real-time comparison vs daily kill-switch limit | 1d |
| P1.8 | Audit trail: fill → order → signal → strategy linkage | 1d |
| P1.9 | Order amendment on stale limit prices | 1d |
| P1.10 | Execution quality measurement (actual vs expected fill) | 1d |

---

### TIER 2 — Strategy Edge (2-4 weeks)
*Goal: Real edge. Paper Sharpe > 0.8 with realistic fills.*

| # | Item | Effort |
|---|---|---|
| P2.1 | Wire stat_arb.py into StrategyGenAgent with cointegration test | 2d |
| P2.2 | Multi-timeframe confirmation (1-min signal + 15-min trend) | 1d |
| P2.3 | Earnings calendar filter (block entries on result day ± 1) | 1d |
| P2.4 | Walk-forward backtest gate before strategy promotion | 2d |
| P2.5 | Depth-weighted order book slippage model | 2d |
| P2.6 | Train meta-labeler (need 1000+ labeled samples) | 3-5d |
| P2.7 | Replace fixed 1% risk with fractional Kelly from realistic fills | 1d |
| P2.8 | Timestamped historical data pipeline (not synthetic) | 2d |
| P2.9 | Corporate actions adjustment (splits, bonuses, dividends) | 1d |
| P2.10 | Tick validation (stale price, zero price, gap detection) | 1d |

**Gate:** 30-day paper run with realistic fills. Sharpe > 0.8, max DD < 8%, win rate > 48%.

---

### TIER 3 — Institutional Readiness (1-3 months)
*Goal: Measurable, observable, recoverable live trading.*

| # | Item | Effort |
|---|---|---|
| P3.1 | Full order book integration (Zerodha WebSocket depth) | 2d |
| P3.2 | Prometheus alert rules (KillSwitch, agent down, broker disconnect) | 1d |
| P3.3 | PagerDuty/Telegram on-call for critical alerts | 1d |
| P3.4 | Secret vault for Kite token rotation | 1d |
| P3.5 | CNC/NRML product type for overnight/swing | 2d |
| P3.6 | SEBI algo registration compliance review | 1d |
| P3.7 | P&L attribution per strategy per day for tax reporting | 1d |
| P3.8 | Log aggregation (Loki / CloudWatch) | 1d |
| P3.9 | Heartbeat/watchdog detecting hung agents | 1d |
| P3.10 | Railway static egress IP (Pro plan or proxy) | 1d |

**Gate:** 30-day live run with ≤ ₹10,000 capital. Real slippage matches model within 2×.

---

### TIER 4 — Competitive Parity & Advantage (3-6 months)
*Goal: Match or exceed OpenAlgo capabilities in areas that matter.*

| # | Item | Effort |
|---|---|---|
| P4.1 | Multi-broker order execution (Angel + Groww full integration) | 1-2 months |
| P4.2 | No-code strategy flow builder (differentiator vs drag) | 2-3 months |
| P4.3 | Options analytics suite (OpenAlgo has 12 tools) | 2-3 months |
| P4.4 | Community documentation + Discord | Ongoing |
| P4.5 | CI/CD for strategy deployment | 1 week |
| P4.6 | Microstructure signal (order flow imbalance, bid/ask pressure) | 2-4 weeks |
| P4.7 | ML regime predictor (Dilated CNN per NSE research) | 2-4 weeks |

---

## Part C — Competitive Landscape

### Direct Competitors for NSE Algo Trading

| Platform | Type | Brokers | Stars | Key Strength | Key Weakness |
|---|---|---|---|---|---|
| **OpenAlgo** | Full platform | 30+ | ~2023 | No-code builder, options suite, 30+ brokers, active community (180 Discord) | Limited to strategy hosting/bridge; no multi-agent architecture |
| **Options-Trading-Bot** | CLI bot | 1 (Kite) | ~9 | Clean MIT license, backtest+paper+live | Only options, minimal community |
| **Nubra API** | Broker SDK | 1 (Zanskar) | N/A | <5ms latency, SEBI-registered broker | Single broker, not open source |
| **Freqtrade** | Crypto bot | 10+ crypto | ~35k | Mature, Telegram control, ML hyperopt | Crypto-only; not applicable to NSE |
| **Your system** | Multi-agent | 1 (Kite) + 2 data | Private | Multi-agent, reflection engine, regime detection, portfolio optimization | No community, 1 full broker, zero edge strategies currently |

### Your Advantages vs OpenAlgo
- Multi-agent architecture with reflection engine & LLM integration
- Academic-grade portfolio optimization (Ledoit-Wolf, risk parity)
- Regime detection with regime-aware weight multipliers
- Event-driven architecture with pluggable backends
- Better code quality per-line (Pydantic settings, typed schemas, mypy)

### OpenAlgo Advantages Over You
- 30+ fully integrated brokers (vs your 1)
- No-code strategy builder (vs your Python-only)
- Options analytics suite (12 tools)
- 100K+ downloads, 2K+ GitHub stars, active community
- Docker self-hosted with nginx, CSP headers, rate limiting
- AGPL-3.0 license (yours is MIT — less restrictive, good for adoption)

---

## Part D — NSE Microstructure Research Implications

### Key Findings Applied to Your System

| Research Finding | Source | Implication for Your System |
|---|---|---|
| **NSE volatility is U-shaped**: peak at 9:15-10:00 and 14:30-15:30 | Sampath & Gopalaswamy (2020) | VWAP reversion should target midday (11:30-14:00). But EMA200 filter blocks till 12:35 — only 25min of reversion window left! |
| **NSE liquidity also U-shaped**: wider spreads at open despite higher volume | Krishnan & Mishra (Monash) | Paper fills at last price overstate execution quality by 2-5x during open/close. Add spread-aware slippage. |
| **Positive volume impact asymmetry**: buy volume > sell volume impact | Gopalaswamy & Sampath (2018) | Volume confirmation should be asymmetric: buy signals with volume are more reliable than sell signals with volume. Your current model is symmetric. |
| **Dilated CNN outperforms GARCH for NSE volatility** | Vempati Madhubabu (2025) | Meta-labeler could benefit from CNN-based volatility regime instead of simple ADX classification. |
| **Trade-time vs calendar-time bias**: U-shape partially an artifact | Barardehi & Bernhardt (2025) | Your 1-min fixed-interval bars overstate open/close volatility. Trade-time bars would give more accurate signals. |
| **Zerodha Kite API**: static IP mandatory from April 2025 | Zerodha support docs | You MUST configure static IP before live orders. Railway users need Pro plan or Cloudflare Tunnel. |

### Timing Optimization for Current Strategies

Based on U-shape research, optimal strategy activation windows:

| Strategy | Best Window (IST) | Current Window | Gap |
|---|---|---|---|
| Momentum (TSMOM) | 9:30-10:30, 14:00-15:00 | All day (cold-start 20min) | OK after P0.1 fix |
| VWAP Reversion | 11:30-14:00 (midday chop) | 12:35-15:30 (EMA200 gate) | MISSING 11:30-12:35 window |
| Sideways Reversion | 11:30-14:00 | 12:35-15:30 | MISSING 11:30-12:35 window |

**Problem:** The best reversion window (11:30-14:00) overlaps partially with EMA200 cold-start (till 12:35). Fix by reducing EMA lookback.

---

## Summary: What to Do First

```
Priority order:
1. Fix TSMOM timeframe (40% weight = wrong signals)
2. Persistent kill switch (crash during crash = real money loss)
3. Configure Kite static IP (orders will be rejected without it)
4. Realistic fill model (paper data is dangerously misleading)
5. SQLite → Postgres (will fail under load)
6. Broker reconnect (tick loss during market hours)
7. Reduce EMA200 cold-start (53% of session wasted)
8. Fix memory leak (runs fine for days, crashes after weeks)
9. Metrics persistence (can't improve what you can't measure)
10. Pre-trade checklist (safety net before any live order)
```

**Existing plan.md bugs 1-10 are already fixed.** Do not regress them. This PLAN2 adds what they missed.
