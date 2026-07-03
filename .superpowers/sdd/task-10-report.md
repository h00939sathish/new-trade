# Task 10: End-to-End Backtest Validation Script for FX

## Status: ✅ Complete

## Files Created
- `scripts/run_system_backtest_oanda.py` — FX backtest script

## What It Does
1. Replaces the global `AsyncEventBus` with `SyncEventBus` for synchronous event delivery
2. Creates a `TradingSystem` without real brokers (paper trading mode)
3. Sets exchange to `FX` and registers instruments `XAUUSD=X`, `EURUSD=X`
4. Loads FX-specific strategy configs via `load_oanda_profile("XAU_USD")` and `load_oanda_profile("EUR_USD")`
5. Registers FX strategies (momentum, vol_breakout, sideways_reversion, ema200_regime_gate, adx_regime_filter for XAU; momentum, sideways_reversion, vol_breakout, ema200_regime_gate, adx_regime_filter for EUR)
6. Patches agents to prevent background loops and patches execution for synchronous risk-check handling
7. Fetches 1m historical candles from Yahoo Finance for both symbols
8. Injects candles into the pipeline (MarketIntel → StrategyGen → RiskMgmt → Execution)
9. Reports candle counts, fill counts (buys/sells), PnL, capital, and positions summary

## Test Results
- Script runs without errors for `--days 1` (1,439 candles fetched per symbol)
- Pipeline fully executes: signals were generated (2 pending at shutdown), though no fills occurred due to strategy thresholds/conservative FX parameters
- `pytest tests/connectors/test_backtest_provider_fx.py -v` passes

## Execution
```
python scripts/run_system_backtest_oanda.py --days 30
```
