# Task 8 Report: Wire OANDA into TradingSystem

## Status: ✅ Complete

### Changes Made

**`src/system.py`**
- Added `Exchange` import at top level (line 19)
- Added `_oanda_provider` and `_oanda_broker` instance attributes (lines 29-30)
- Added OANDA provider detection block inside the `else` branch (lines 62-72) — creates `OandaClient`, `OandaMarketDataProvider`, and conditionally `OandaBroker` when `oanda_execution_mode == "oanda_practice"`
- Updated `market_data_provider` selection to prefer OANDA before Angel/Groww/Jugaad (line 81)
- Added broker selection variable `broker = self._oanda_broker or self._kite_broker` (line 95)
- Updated `ExecutionAgent` to use `broker` instead of `self._kite_broker` (line 98)
- Added FX instrument watchlist population after `market_intel` creation (lines 87-92) — adds each instrument from `oanda_enabled_instruments` and sets exchange to `Exchange.FX`

**`tests/test_system_oanda.py`** (new)
- `TestSystemOandaWiring.test_system_detects_oanda_settings` — verifies `_oanda_provider` is created and `_oanda_broker` is `None` when `oanda_execution_mode == "internal_simulation"`
- `TestSystemOandaWiring.test_oanda_broker_created_in_practice_mode` — verifies `_oanda_broker` is created when `oanda_execution_mode == "oanda_practice"`
- Tests use module unloading pattern to ensure clean imports within patched context

### Test Results

```
tests/test_system_oanda.py::TestSystemOandaWiring::test_system_detects_oanda_settings PASSED
tests/test_system_oanda.py::TestSystemOandaWiring::test_oanda_broker_created_in_practice_mode PASSED
```

Full regression suite: **24 passed** (test_system_oanda + test_agents + test_integration)
OANDA connector tests: **20 passed**
