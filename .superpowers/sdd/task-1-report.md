# Task 1 Report: Exchange Enum, AssetClass, and Settings

**Status:** DONE

## Changes Made

### `src/schemas/events.py` (line 81)
- Added `FX = "FX"` to the `Exchange` enum

### `src/config/settings.py` (lines 107-111)
- Added 5 OANDA settings fields after the MCX gold settings:
  - `oanda_api_key: str = ""`
  - `oanda_account_id: str = ""`
  - `oanda_environment: str = "practice"`
  - `oanda_enabled_instruments: str = "XAU_USD,EUR_USD"`
  - `oanda_execution_mode: str = "internal_simulation"`

Key: All five use plain `str = default` (matching existing code style) rather than `pydantic.Field`.

### AssetClass Verification
- `AssetClass.CURRENCY` (line 70) and `AssetClass.COMMODITY` (line 69) already exist — no changes needed.

## Test Results
- `tests/test_ml_regime.py` — ModuleNotFoundError (pre-existing, missing module `src.strategies.ml_regime`)
- `tests/ -x` failure on the first hit was `test_market_data_provider_falls_back_to_polling_after_websocket_disconnect` (pre-existing flaky async test)
- All other tests (30 passed) unaffected by the changes

The two failures are pre-existing and unrelated to Task 1.

## Commit
```
de8c480 feat(oanda): add Exchange.FX and OANDA settings
```
