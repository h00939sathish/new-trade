# Task 6: FX Instrument Profiles — Report

## Files Created

| File | Purpose |
|---|---|
| `src/config/oanda_profiles.py` | Instrument profiles + `load_oanda_profile()` merger |
| `tests/config/test_oanda_profiles.py` | 6 tests covering profiles, disabled flags, merge, unknown instrument |
| `tests/config/__init__.py` | Package init for test discovery |

## Exported Interface

- **`OANDA_INSTRUMENT_PROFILES`** — `dict` with `"XAU_USD"` and `"EUR_USD"` keys, each containing `strategies` (strategy weights/params) and `instrument_meta` (asset class, pip location, max spread, etc.)
- **`load_oanda_profile(instrument: str) -> dict`** — deep-copies `DEFAULT_CONFIG` and overlays the profile's strategy overrides

## Profile Summary

| Instrument | Momentum | Vol Breakout | Sideways Rev | VWAP Rev | Stat Arb | EMA200 | ADX |
|---|---|---|---|---|---|---|---|
| **XAU_USD** | 0.6 ✅ | 0.4 ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **EUR_USD** | 0.5 ✅ | 0.2 ✅ | 0.3 ✅ | ❌ | ❌ | ✅ | ✅ |

## Test Results

```
tests/config/test_oanda_profiles.py .............. [100%]
6 passed in 5.34s
```
