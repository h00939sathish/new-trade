# Task 3: OANDA Market Data Provider — Report

## Status
Complete.

## Commits
- `fd11db9` — `feat(oanda): add OANDA market data provider`

## Test Summary
- **3/3 passed** in 1.46s
  - `test_add_instrument_and_start` — verifies `add_instrument` tracks instruments
  - `test_callbacks_are_set` — verifies `set_tick_callback` / `set_ohlcv_callback` store callbacks
  - `test_get_historical_returns_candles` — verifies `get_historical` parses OANDA candles into OHLCV format

## Files Changed
| File | Action |
|------|--------|
| `src/connectors/oanda/market_data.py` | Created (235 lines) |
| `src/connectors/oanda/__init__.py` | Updated — added `OandaMarketDataProvider` export |
| `tests/connectors/oanda/test_market_data.py` | Created (62 lines) |

## Concerns
- The `get_historical` test uses a sync `MagicMock` for `OandaClient.get_candles` — that's fine since `get_candles` is sync. No async mocking needed for this path.
- `start()` requires a real `OandaClient` to do anything meaningful (logs a warning and returns if `_client` is `None`), which is the same pattern as other providers.
- The coverage threshold (80%) in `pyproject.toml` will continue to fail on the full suite until overall coverage improves — this is a pre-existing concern, not specific to this task.

## Report Path
`D:\projects\new trade\.superpowers\sdd\task-3-report.md`
