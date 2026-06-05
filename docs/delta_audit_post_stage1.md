# Delta Audit — June 5, 2026 (post-Stage-1)

This document compares the **prior full audit** (received from the user
on 2026-06-05) against the **current state of the code on disk** as of
2026-06-05, after Stage 1 fixes were applied.

Format: each claim from the prior audit is checked against the current
code, and a verdict is given.

---

## 1. Claim: "ExecutionAgent._handle_risk_check has UnboundLocalError on order_validation"

**Prior audit verdict**: STILL BROKEN

**Current state**: **FIXED**

**Evidence**:
- `src/agents/execution.py:433-475` (read at audit time)
- Lines 441-442 read `passed` and `details` BEFORE the
  `if check_name == "order_validation":` branch
- Comment in code: "FIX P0.1: read `passed` and `details` BEFORE any
  conditional branch to avoid UnboundLocalError. Original code defined
  these at line 456 but referenced them at lines 439 and 452."
- Commit `ebdd65f` (2026-06-05) is the fix.
- Verified at runtime: reproduction script from earlier in this session
  printed "OK P0.1a: order_validation flow did not crash".

**Action**: Prior audit was correct about the bug, but the fix is already
in place. Remove this from "still broken" list.

---

## 2. Claim: "RiskManagementAgent._validate_order uses self._capital which is never initialized"

**Prior audit verdict**: Not specifically listed in the prior audit's
table, but the early audit found this bug. Listed as
"STILL BROKEN" implicitly.

**Current state**: **FIXED**

**Evidence**:
- `src/agents/risk_mgmt.py:31-33`
- `self._capital = settings.reflection_initial_capital` in `__init__`
- Commit `ebdd65f` includes the fix
- Runtime reproduction: "OK P0.2: _validate_order did not crash,
  _capital initialized to: 1000000.0"

---

## 3. Claim: "Regime weight logic uses absolute overrides that kill strategies outside their preferred regime"

**Prior audit verdict**: NOT IDENTIFIED in the prior audit.

**Current state**: **FIXED** (but was a real bug)

**Evidence**:
- Old code (`strategy_gen.py:128-159` pre-fix):
  - momentum in mean_reverting → weight 0.02 → impossible to fire
  - reversion in trending_up → weight 0.02 → impossible to fire
- New code (`strategy_gen.py:143-159`):
  - Multipliers bounded [0.3, 2.0]
  - momentum in mean_reverting: 0.4 × 0.70 = 0.28 effective weight
- Verified directly:
  - Before: momentum at conf=0.5 in mean_reverting → vote = 0.010
  - After: momentum at conf=0.5 in mean_reverting → vote = 0.216
- Commit `a1adaa4` (2026-06-05) is the fix.

**Why the prior audit missed this**: the audit looked for crashes and
connectivity issues, not for silent weight assignments that prevent
signal generation. The system was running "correctly" — it just
correctly returned no signals.

**Action**: Add this to the audit as a **regression vs the old
`TRADE/` repo**, fixed in `a1adaa4`.

---

## 4. Claim: "Position registry is SSOT"

**Prior audit verdict**: "YES — for quantity. PositionRegistry is the
declared SSOT and is used consistently."

**Current state**: **CONFIRMED**

**Evidence**:
- `src/risk/position_registry.py` is a singleton
- ExecutionAgent reads via `_get_position_qty()`
- RiskManagementAgent reads via `get_position()`
- StrategyGenAgent reads in `_process_fill`
- PortfolioOptimizationAgent writes via
  `position_registry.update_from_fill()`

**Caveat (not raised in prior audit)**: The PortfolioOptimizationAgent
also maintains its own `_positions` dict. The two are kept in sync only
because `_on_fill` calls both. If a fill arrives at the registry
without going through the portfolio agent (e.g., via reconciliation),
they diverge. This is the same caveat the prior audit mentioned under
"divergence only if a fill arrives at the registry without going
through the portfolio agent".

**Action**: This is the next thing to fix (Stage 2 P1.1 in the three
stage roadmap).

---

## 5. Claim: "Stop-loss is not automated for live positions because trigger_price is never set"

**Prior audit verdict**: "PARTIALLY VERIFIED" — code upgrades to CO
if trigger_price is provided, but trigger_price is not set upstream.

**Current state**: **CONFIRMED UNCHANGED**

**Evidence**:
- `src/agents/execution.py:605-622`: upgrades to `variety="co"` if
  `trigger_price` is provided and > 0
- `grep trigger_price src/agents/strategy_gen.py src/agents/risk_mgmt.py`
  returns nothing — no upstream code sets it
- So MIS orders are placed as plain market orders, no native SL

**Action**: This is a real P1 issue. To fix: in
`_execute_approved_signal`, compute `trigger_price = price * (1 - sl_pct)`
from the strategy's `sl_pct` and the entry price, and pass it through.

---

## 6. Claim: "ExpertPersonasAgent is DEAD — instantiated nowhere"

**Prior audit verdict**: DEAD

**Current state**: **CONFIRMED**

**Evidence**:
- Imported in `src/agents/__init__.py`
- Not in `system.py:_agents` list
- No instantiation found via grep

**Action**: Remove from `__init__.py` or instantiate. Currently adds
import overhead with no runtime benefit.

---

## 7. Claim: "GeminiClient is dead code — reflection engine uses grid search"

**Prior audit verdict**: REMOVE or comment out

**Current state**: **CONFIRMED**

**Evidence**:
- `src/reflection/gemini_client.py` exists
- `_find_best_mutation` uses Cartesian grid search, not LLM
- Grep for `GeminiClient` returns the file only, no callers in the
  active reflection path

---

## 8. Claim: "11 patch_*.py files in project root are deployment risk"

**Prior audit verdict**: REMOVE

**Current state**: **CONFIRMED**

**Evidence**:
- `ls patch_*.py` returns 11 files
- They are ad-hoc debugging patches
- Risk of accidental execution in a real deploy

---

## 9. Claim: "strategies.yaml at root is dead code"

**Prior audit verdict**: REMOVE

**Current state**: **CONFIRMED**

**Evidence**:
- `strategy_config.py` loads from `DEFAULT_CONFIG`, not the file
- `StrategyGenAgent` is instantiated without `config_path`
- The reflection engine references `config/strategies.yaml` (different
  path) which also doesn't exist; falls back to DEFAULT_CONFIG

---

## 10. Claim: "Position Sizing uses ATR-based stop distance (1% capital risk)"

**Prior audit verdict**: FIXED

**Current state**: **CONFIRMED**

**Evidence**:
- `src/agents/execution.py:648` — `calculate_quantity` now uses
  ATR-based sizing: `risk_per_trade / stop_distance`

---

## 11. Claim: "Paper trading realism 5/10"

**Prior audit verdict**: 5/10

**Current state**: **CONFIRMED**

**Evidence**:
- Cost model is correct (STT, exchange fees, GST, brokerage, stamp)
- Fill model uses real tick + order book depth
- 50-150ms latency simulation is cosmetic
- No partial fills

**Action**: This is acceptable for the current paper-trading validation
phase. Not a blocker.

---

## 12. Claim: "The system cannot complete a round-trip because of the
UnboundLocalError"

**Prior audit verdict**: "This is the only thing blocking a clean paper
trading run."

**Current state**: **OUTDATED** — the UnboundLocalError is fixed
(claim #1). However, **the system still hasn't completed a round-trip
in this session** because:

1. Market is flat (RELIANCE at 1300-1301, 0.1% range)
2. The strategies correctly refuse to trade in flat conditions
3. Angel WebSocket rate limit when local and production both connect
   with the same credentials

The next round-trip will happen on a normal day, not today.

---

## Updated Final Verdict

### What is still broken
- **Stop-loss automation**: trigger_price is not set upstream of
  `_execute_approved_signal`. MIS orders have no native SL. (P1)
- **Position state divergence risk**: PortfolioOptimizationAgent has
  its own `_positions` dict that could diverge from PositionRegistry
  if fills arrive via reconciliation path. (P1)
- **SyncEventBus event-ordering bug**: when RISK_CHECK is emitted
  inside SIGNAL handling, the bus delivers RISK_CHECK to execution
  before SIGNAL — execution never finds the matching pending signal.
  Affects backtester only, not production. (P2)
- **ExpertPersonasAgent, GeminiClient, patch_*.py, root strategies.yaml**:
  dead code / dead config. Cleanup. (P3)

### What is actually fixed
- UnboundLocalError in `_handle_risk_check` (commit `ebdd65f`)
- `_capital` initialization in `RiskManagementAgent.__init__`
  (commit `ebdd65f`)
- Strategy set trimmed to 3 (momentum, sideways_reversion,
  vwap_reversion) (commit `ebdd65f`)
- Regime weight allocation: multiplier-based instead of absolute
  overrides (commit `a1adaa4`)
- Runtime tracing (52 traces in `logs/runtime_traces/traces_20260604.jsonl`)
- Kite `place_order` variety kwarg handling
- Position sizing uses ATR-based stop distance
- Cost model with full Indian market tax breakdown
- Kill switch with daily loss + drawdown triggers
- Two-stage risk gate (signal_validation + order_validation)

### What is unnecessarily complex
- TWAP engine: correct but unreachable at current sizing. Activation
  threshold ≥500 shares which requires ≥₹12.5 lakh notional, larger
  than `risk_max_order_value` of ₹50,000.
- 11 patch_*.py files in root
- root strategies.yaml (the `__init__.py` ignores ignore_list includes
  it; nothing reads it)

### What must be fixed before live trading
1. **Stop-loss automation** (P1, ~30 min): set trigger_price in
   `_execute_approved_signal` from the signal's `sl_pct` and price.
   This makes MIS orders become CO with native broker SL.
2. **Position SSOT enforcement** (P1, ~1 hr): refactor
   PortfolioOptimizationAgent to read from PositionRegistry only. Add
   a test that detects divergence.
3. **30 days of paper trading** with real credentials (P0, ~30 days):
   current data is at most 7 days of Yahoo 1m + production Railway
   flat-day data — neither is a valid validation baseline.

### What I would personally work on next
The SL automation fix. It's ~30 minutes, it directly addresses the
"live trading readiness 4/10" finding, and without it the system
cannot safely be turned on. After that, position SSOT enforcement
(Stage 2 P1.1), then start the 30-day paper run.

The UnboundLocalError is no longer the blocker. That conclusion in
the prior audit is stale.
