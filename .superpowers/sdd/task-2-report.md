# Task 2 Report: OANDA v20 REST Client

**Status:** DONE

## Changes Made

### `src/connectors/oanda/__init__.py` (new)
- Exports `OandaClient` for use by other modules

### `src/connectors/oanda/client.py` (new, ~180 lines)
- `OandaClient(api_key, account_id, environment="practice")` class
- Rejects `"live"` environment and invalid environments with `ValueError`
- Private helpers: `_url()`, `_get()`, `_post()`, `_patch()`, `_delete()` using `httpx`
- Public methods:
  - `get_account_summary()` — GET `/accounts/{id}`
  - `get_instruments()` — GET `/accounts/{id}/instruments`
  - `get_candles(instrument, granularity, count, from_time, to_time, include_first)` — GET candle data
  - `get_candle_bid_ask(instrument, ...)` — GET bid/ask candles
  - `stream_pricing(instruments)` — async generator over pricing stream via `httpx.AsyncClient`
  - `place_order(instrument, units, side, order_type, client_order_id, stop_loss, take_profit)` — POST order
  - `get_orders()`, `get_pending_orders()`, `cancel_order()`, `get_order()`
  - `get_positions()`, `get_position(instrument)`
  - `get_open_trades()`
  - `get_transactions_since(since_id)`, `get_transaction(txn_id)`

### `tests/connectors/oanda/test_client.py` (new, 10 tests)
- Mock-based tests using `unittest.mock.patch` (no `requests_mock` dependency needed)
- Tests: rejects live env, accepts practice, parses instruments, empty candles, invalid env, API error propagation, place_order, cancel_order, stream_pricing

## Test Results
All 10 tests pass:
```
tests/connectors/oanda/test_client.py::TestOandaClient::test_init_rejects_live_env PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_init_accepts_practice PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_raises_on_invalid_environment PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_get_instruments_parses_response PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_get_instruments_empty_response PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_api_error_propagates PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_get_candles_empty_response PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_place_order PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_cancel_order PASSED
tests/connectors/oanda/test_client.py::TestOandaClient::test_stream_pricing PASSED
```

## Concerns
- Tests use `unittest.mock.patch` instead of `requests_mock` (which was suggested in the plan but is not a project dependency). The `httpx` internal client is mocked directly, which is equivalent in coverage.

## Commit
```
f99e988 feat(oanda): add OANDA v20 REST client
```
