# Task 9: Backtest FX Support via Yahoo Finance

## Status: Complete

## Changes Made

### 1. `src/connectors/backtest_provider.py` — Added `"FX": ""` to exchange_map

**Line 299:** Added `"FX": ""` so Yahoo Finance symbols like `EURUSD=X` are fetched without any suffix appended:

```python
exchange_map = {"NSE": ".NS", "BSE": ".BO", "FX": ""}
```

### 2. `src/connectors/backtest_provider.py` — Skip provider call for FX in `get_backtest_ticks`

**Line 66:** Added `self._exchange != "FX"` guard so that FX symbols skip the NSE-specific provider call and go directly to Yahoo Finance:

```python
if self._exchange != "FX" and hasattr(self._provider, "get_historical"):
```

This avoids unnecessary failures from the provider (which doesn't support FX symbols) and goes straight to the fallback Yahoo Finance fetch.

### 3. `tests/connectors/test_backtest_provider_fx.py` — New test file

Tests that FX symbols return real 1m candles from Yahoo Finance with the correct data structure.

## Test Results

| Test | Result |
|------|--------|
| `test_fetch_fx_candles_no_suffix` | PASS |
| Existing `test_backtest_provider.py` (7 tests) | ALL PASS |

## Note

The brief listed `XAUUSD=X` as an FX symbol, but Yahoo Finance does not serve this symbol (404). The test uses `EURUSD=X` which is a valid Yahoo Finance FX pair. Gold spot would use `GC=F` (futures) on Yahoo Finance instead.
