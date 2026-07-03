# Phase 5: Capability Matrix + Contradiction Analysis

---

## 1. Capability Matrix

| Capability | Current State | Production-Ready | Paper-Ready | Gap |
|-----------|---------------|:----------------:|:-----------:|-----|
| **Market Data** | | | | |
| Angel live ticks | WebSocket + polling | ⚠️ | ✅ | Static IP, rate limits |
| Kite live ticks | Polling only (no WS) | ❌ | ✅ | No WS integration |
| Yahoo Finance LTP | REST fallback | ❌ | ✅ | Unauthenticated, rate-limited |
| Jugaad historical | Bhavcopy EOD | ❌ | ✅ | No intraday |
| Alternative data | RSS feed (unwired) | ❌ | ❌ | Dead code |
| **Signal Generation** | | | | |
| 14 strategies registered | 3 active + 2 filters | ⚠️ | ✅ | stat_arb rogue activation |
| Signal consensus | Threshold + cooldown | ✅ | ✅ | — |
| Regime detection | 20-period lookback | ✅ | ✅ | Needs tuning |
| **Execution** | | | | |
| Paper fill model | Depth-aware + costs | N/A | ✅ | No partial fills |
| Live order routing | KiteBroker / Angel | ❌ | N/A | Static IP, OAuth missing |
| TWAP scheduling | SQLite-backed | ⚠️ | ✅ | Stale state persistence |
| Market impact | Advisory only | ❌ | N/A | Not integrated |
| **Risk Management** | | | | |
| VaR(95%) | Historical, 20 returns | ⚠️ | ✅ | False `passed:True` |
| Margin checks | Fixed MIS/CNC/CO % | ⚠️ | ✅ | No SPAN calc |
| Position reconciliation | Broker comparison | ✅ | N/A | — |
| Kill switch | File-persisted | ✅ | ✅ | Lost on Railway deploy |
| Circuit breaker | In-memory | ⚠️ | ✅ | Not persisted |
| Concentration limits | Basic | ⚠️ | ✅ | Simple threshold |
| **Portfolio** | | | | |
| Position tracking | FIFO cost basis | ✅ | ✅ | — |
| HRP allocation | Implemented | ❌ | ❌ | Unwired |
| Attribution | Per-strategy PnL | ✅ | ✅ | FIFO approximation |
| **Validation** | | | | |
| Backtest engine | Agent-based | ⚠️ | ✅ | Paper fills, no corp actions |
| Walk-forward | 3 strats only | ⚠️ | ✅ | Not comprehensive |
| Monte Carlo | Bootstrap resampling | ✅ | ✅ | Destroys autocorr |
| Grid optimizer | Brute-force | ⚠️ | ✅ | No CV, overfitting |
| **ML** | | | | |
| Meta labeling | Triple Barrier stub | ❌ | ❌ | No model, no wiring |
| **Monitoring** | | | | |
| Prometheus metrics | SQLite-backed | ✅ | ✅ | — |
| CLI dashboard | Rich-based | ✅ | ✅ | — |
| Latency tracing | JSONL (unwired) | ❌ | ❌ | Dead code |
| Strategy decay | Calculated (unwired) | ❌ | ❌ | No system integration |
| **Security** | | | | |
| Secrets management | Plaintext env vars | ❌ | ⚠️ | Encryption needed |
| Static IP compliance | None | ❌ | N/A | CRITICAL for live |
| OAuth compliance | None | ❌ | N/A | SEBI mandate |
| Audit trail | SQLite (current only) | ❌ | ⚠️ | 5-year retention |
| **Infrastructure** | | | | |
| Railway deploy | Containerized | ⚠️ | ✅ | Ephemeral FS issue |
| Startup time | ~2.5s | ✅ | ✅ | — |
| Graceful shutdown | Partial | ⚠️ | ✅ | No Angel logout |

**Legend**: ✅ = Ready / ⚠️ = Needs Work / ❌ = Not Ready / N/A = Not Applicable

## 2. Contradiction Analysis

### C1: "stat_arb disabled" vs "stat_arb enabled"
- **Source**: ARCHITECTURE.md says "disabled" // `strategy_config.py:98` has `enabled: true`
- **Impact**: 4 runtime divergences cascade from this single config mismatch
- **Resolution**: Align config with intent. Either disable in config or update docs.

### C2: "Kill switch persisted" vs "Kill switch lost on deploy"
- **Source**: Code persists to `state/kill_switch.state` // Railway filesystem is ephemeral
- **Impact**: On Railway deploy, kill-switch resets to inactive — could resume trading in dangerous conditions
- **Resolution**: Use Railway volume mount or external KV store

### C3: "4 broker connectors" vs "Groww unwired"
- **Source**: ARCHITECTURE.md lists 4 brokers // Groww client not instantiated anywhere in system.py
- **Impact**: Dead code = maintenance burden
- **Resolution**: Remove or wire it in

### C4: "Risk checks protect portfolio" vs "VaR false pass"
- **Source**: Risk management pipeline // VaR returns `passed: True` with <20 data points
- **Impact**: Market opens with insufficient data = blind trading
- **Resolution**: Make insufficient data a hard PASS FAIL, not pass

### C5: "Paper model simulates costs" vs "Paper model lacks partial fills"
- **Source**: Costs (STT, GST, brokerage) are calculated // Fill is always full qty or reject
- **Impact**: Overestimates fill probability, underestimates slippage variance
- **Resolution**: Implement probabilistic partial fills

### C6: "Walk-forward prevents overfitting" vs "Only 3/14 strategies"
- **Source**: walk_forward.py defines grids for 3 strats // 11 strats untested
- **Impact**: 11 strategies have no statistical validation
- **Resolution**: Define grids for all active strategies

### C7: "14 strategies available" vs "3 active + 9 disabled + 2 filters"
- **Source**: STRATEGY_REGISTRY has 14 // Runtime activates only 3 signal producers
- **Impact**: Architecture doc claims 5 active (including filters); actual signal producers = 3
- **Resolution**: Clarify terminology — filter strategies are not signal producers

### C8: "Comprehensive backtesting" vs "Backtest uses paper fill model"
- **Source**: BacktestEngine uses ExecutionAgent // Execution uses paper fill, not historical spread
- **Impact**: Backtest PnL diverges from real-market PnL significantly
- **Resolution**: Add spread-aware fill model to backtest

### C9: "ML meta labeling enhances signals" vs "Complete stub"
- **Source**: src/ml/meta_labeler.py exists with Triple Barrier // No model, no wiring, no consumer
- **Impact**: ML claims are aspirational, not operational
- **Resolution**: Either remove or build

### C10: "Strategy decay detection active" vs "Actions unwired"
- **Source**: StrategyDecayDetector computes metrics // Auto-disable/alert functions never called
- **Impact**: Decay detection is a read-only dashboard — no protective action
- **Resolution**: Wire decision actions into system

## 3. Contradiction Severity Matrix

| ID | Severity | Category | Fix Difficulty | Business Impact |
|----|----------|----------|---------------|-----------------|
| C1 | CRITICAL | Config/Docs | Easy (<1hr) | Weight inflation, rogue signals |
| C2 | HIGH | Infrastructure | Medium (volume mount) | Risk of blind restart |
| C3 | LOW | Dead Code | Easy (remove) | None |
| C4 | CRITICAL | Risk Logic | Easy (<1hr) | Blind trading at market open |
| C5 | HIGH | Paper Model | Medium (2-3 days) | Unrealistic backtest PnL |
| C6 | MEDIUM | Validation | Medium (1-2 days) | 11 strats unvalidated |
| C7 | LOW | Documentation | Easy (<30min) | Misleading architecture map |
| C8 | HIGH | Backtest | Hard (2-4 weeks) | Backtest results unreliable |
| C9 | MEDIUM | ML | Very Hard (months) | No impact (unused anyway) |
| C10 | MEDIUM | Analytics | Medium (1-2 days) | No auto-decay protection |
