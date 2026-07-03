# Task 7: USD Risk Sizing — Complete

## Files Created

| File | Description |
|------|-------------|
| `src/risk/oanda_sizing.py` | Risk sizing module with `calculate_oanda_units` and `validate_oanda_order` |
| `tests/risk/test_oanda_sizing.py` | 13 tests covering all functions and edge cases |
| `tests/risk/__init__.py` | Package init for test discovery |

## Implementation

**`src/risk/oanda_sizing.py`** — Implements two functions:

- `calculate_oanda_units(equity_usd, entry_price, stop_price, instrument_meta) -> int`  
  Formula: `floor(equity * 0.005 / abs(entry - stop))` rounded down to `trade_units_precision`. Returns 0 if below `minimum_trade_size` or stop distance is zero.

- `validate_oanda_order(equity_usd, units, entry_price, stop_price, instrument_meta, combined_risk) -> tuple[bool, str]`  
  Validates units positive, prices positive, entry != stop, combined risk below threshold, new trade doesn't exceed max combined risk, and units >= minimum trade size.

**Constants:**
- `RISK_PER_TRADE = 0.005` (0.5%)
- `MAX_COMBINED_RISK = 0.01` (1%)
- `DAILY_LOSS_LIMIT = 0.02` (2%)

## Test Results

```
13 passed in 5.99s
src/risk/oanda_sizing.py      36      0   100%
```

### Tests implemented

| Test | What it covers |
|------|---------------|
| `test_calculate_units_basic` | Basic unit calculation with floor rounding |
| `test_calculate_units_below_minimum` | Returns 0 when below `minimum_trade_size` |
| `test_validate_oanda_order_accepts` | Validation passes for valid order |
| `test_validate_oanda_order_rejects_excessive_combined_risk` | Rejects when combined_risk already >= MAX |
| `test_zero_stop_distance_returns_zero` | `calculate_oanda_units` returns 0 when entry == stop |
| `test_negative_prices_validation_rejects` | `validate_oanda_order` rejects negative prices |
| `test_precision_rounding` | Precision=1 with exact division |
| `test_precision_rounding_fractional` | Precision=1 with fractional result floored |
| `test_validate_rejects_zero_units` | Rejects zero units |
| `test_calculate_units_precision_2dp` | Precision=2 rounding |
| `test_validate_rejects_when_combined_plus_new_exceeds_max` | Rejects when combined + new > MAX |
| `test_validate_rejects_zero_stop_distance` | Rejects validate when entry == stop |
| `test_validate_rejects_below_min_size` | Rejects when units below `minimum_trade_size` |
