# Old vs New Trading System Comparison

Date: 2026-06-05
Author: Hermes audit

## Overview

| Aspect | Old `trading_system` (TRADE/) | New `new-trade` |
|---|---|---|
| Lines of code (agents) | 4289 | 5233 |
| Agents | 13 | 9 |
| Regimes detected | 6 (bull, bear, sideways, volatile, trending, mean_reverting) | 4 (trending_up, trending_down, mean_reverting, high_volatility) |
| Regime→weight mechanism | **Multipliers** (bounded 0.65-2.25) | **Absolute overrides** (0.02-0.5) |
| Min confidence filter | yes (`min_confidence`, `min_consensus_strategies`) | no (single threshold) |
| Conflict penalty | yes (entropy-based) | no (relies on sign cancellation) |
| Confidence calibrator | yes (isotonic regression, 8 strategies) | no |
| Smoothing for regime changes | yes (2-bar confirmation) | yes (240s debounce) |
| Strategy grouping | yes (trend/breakout/reversion/filter) | yes (same) |
| Position SSOT | multiple stores, no clear winner | position_registry (declared) but portfolio_opt duplicates |
| Execution | 520 lines | 1359 lines (heavier, more features) |

## Critical Difference Found in This Comparison

### Regime weight logic

**Old system** (`signal_aggregation.py:_rule_based_regime_weights`):
```python
multipliers_by_regime = {
    "bull":     {"momentum": 1.35, "mean_reversion": 0.85, ...},
    "bear":     {"momentum": 0.45, "mean_reversion": 1.10, ...},
    "sideways": {"momentum": 0.80, "mean_reversion": 1.35, ...},
    "volatile": {"momentum": 0.75, "mean_reversion": 0.95, ...},
}
# Result: weight * multiplier, then normalize
```

**New system (before fix)** (`strategy_gen.py:_handle_system_state`):
```python
if regime == "mean_reverting":
    if name in _TREND_STRATEGIES:  # momentum
        self._strategy_weights[name] = 0.02   # KILLS momentum
    elif name in _REVERSION_STRATEGIES:
        self._strategy_weights[name] = 0.5
```

**Impact**: A high-confidence (0.5) momentum signal in a mean_reverting
market produced a vote of `0.02 × 0.5 = 0.010`. The consensus threshold
is 0.15. **No momentum signal could ever fire in mean_reverting regime.**

**Fix applied (commit a1adaa4)**: switched to multiplier-based scaling
bounded [0.3, 2.0]. Verified that momentum at conf=0.5 in mean_reverting
now produces vote = 0.216 (above threshold).

## Other Notable Differences

### Confidence calibration

The old system has `agents/confidence_calibrator.py` (208 lines) that
maps raw strategy confidence to actual P(profitable trade) using
isotonic regression. It fits from a trade log of ≥30 trades per
strategy and stores to `models/calibrator.pkl`. After fitting, all
strategy confidence values pass through the calibrator.

The new system has no calibrator. Raw strategy confidence is used as-is.

**Implication for new-trade**: Even if signals fire, the confidence
numbers don't reflect historical win rates. The 0.5 from momentum means
"5-period short-MA crossed 20-period long-MA by 0.5%", not "I expect
50% probability of profit".

### Smoothing

Old: 2-bar confirmation before regime change.
New: 240-second (4-min) debounce.

The new system's debounce is **time-based**, the old is **bar-based**.
In a 1-minute candle system, 240s = 4 bars, similar effect. But
in higher timeframes (5m, 15m), the old system adapts faster.

### Conflict penalty

Old: when strategies disagree, confidence is reduced by entropy-based
penalty: `confidence *= (1 - conflict_entropy * strength)`. The
penalty can fully cancel a signal if all strategies disagree equally.

New: no conflict penalty. Disagreeing strategies just cancel via
sign in the vote sum, which is brittle when one strategy has
slightly higher confidence than the others.

### Min consensus

Old: requires at least N strategies agreeing (default 1).
New: no such filter.

The old system's `min_consensus_strategies=1` is loose, but having
the option to require 2+ strategies to agree is useful for filtering
out lone-wolf signals in noisy regimes.

## What new-trade Does Better

- **Cleaner module structure** — `src/agents/`, `src/risk/`, etc. are
  well-separated. The old repo has everything in `agents/`.
- **Explicit position_registry** — declared as the single source of
  truth. Old repo didn't have this concept.
- **Live tracing** — `latency_tracer.py` with JSONL. Old repo didn't
  have runtime tracing at all.
- **Real cost model** — `src/risk/costs.py` has full Indian market
  tax breakdown. Old repo has flat `transaction_cost_bps`.
- **Burnin reconciliation** — paper-mode reconciliation JSONL. Old
  repo didn't have this either.

## Verdict

The new-trade system is **structurally cleaner** but has **one critical
regression vs the old repo**: the regime weight logic collapsed from
multipliers to absolute overrides, which silently kills any strategy
outside its preferred regime. This regression alone explains the
"0 signals" finding from the audit.

**Fix applied**: commit a1adaa4 restores multiplier-based regime
weighting matching the old repo's design.

## Recommendations (deferred)

These are NOT in scope for Stage 1 P0.7. Listed for Stage 2/3 reference.

1. **Port the confidence calibrator** from old → new. Requires ≥30
   closed trades per strategy, so this is a Stage 3 task.
2. **Add conflict penalty** to the signal aggregation in new-trade.
   Simple additive change to strategy_gen._process_ohlcv.
3. **Make min_consensus_strategies configurable** via settings.
4. **Add 2-bar confirmation** to regime detection (or keep 240s if
   1-min candles).
