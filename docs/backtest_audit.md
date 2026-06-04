# Backtest Audit — 2026-06-05

## Setup

- 3 strategies enabled (P0.4): momentum, sideways_reversion, vwap_reversion
- Watchlist: RELIANCE
- Period: 7 days of cached 1-min candles (1876 ticks)
- 2026-05-29 04:45 UTC to 2026-06-04 10:00 UTC

## Result

```
Total Ticks Processed: 1876
Total Trade Fills Generated: 0
Total P&L: 0.00
Current Capital: 0.00 (read by bug — actually 1,000,000)
Total Positions: 0
```

**The backtest produced zero trades.**

## Why

The strategies themselves DO produce signals on this data. Direct unit-test
verification (calling each strategy with the cached candles):

| Strategy | Raw signals | Notes |
|---|---|---|
| momentum | 141 | short bias early, then long |
| sideways_reversion | 126 | long bias |
| vwap_reversion | 58 | long bias |

Ensemble voting with threshold=0.2 should produce ~126 signals (the
sideways_reversion signals alone cross the threshold at confidence 0.77).
Verified by direct test: `i=69 ts=2026-05-29 04:54:00+00:00 net=0.268`
etc.

But the **strategy_gen agent emits 0 or 1 signals** when run through the
backtest's `SyncEventBus`. The 1 signal that did fire was at the very
end of the data (a degenerate flat-price region).

## Root cause: SyncEventBus event-ordering bug

The `src/backtest/sync_bus.py` routes events synchronously. When
`strategy_gen` emits a SIGNAL, the bus calls `risk_mgmt.on_event(SIGNAL)`
which processes synchronously and emits a `RISK_CHECK`. The bus
**immediately** routes the RISK_CHECK to `execution.on_event` —
**before** the original SIGNAL is routed to execution.

Trace from instrumented run:

```
>>> EXEC_HANDLE_RISK check_name=signal_validation passed=True
    sig_id_in_pending=False pending_keys=[]
>>> EXEC_HANDLE_SIG event_id=ea95456f7d634443920e8d3505b90a37
    sig_data_keys=[...no _signal_event_id...]
Final: pending=1 filled=0
```

The execution agent receives the RISK_CHECK with a `_signal_event_id`
that it has never seen (because the SIGNAL hasn't been processed yet).
`_pending_signals` is empty when the risk check arrives, so the order
is never created.

The risk-approved signal then arrives as a SIGNAL event, but
`_handle_signal` only handles neutral/exit signals or stores the signal
in `_pending_signals` for a NEW risk check — which never comes.

## What this means for the production system

The production `AsyncEventBus` queues events and processes them in
order. The SyncEventBus bug does NOT affect production. The smoke test
from P0.6 (`scripts/run_first_trade_paper.py`) showed real BUY fills
happening with the production bus.

## What this means for backtesting

Backtesting through `scripts/run_system_backtest.py` is currently
broken. The reported "0 fills" is a backtest infrastructure bug, not a
strategy result.

**Options to fix the backtester** (out of Stage 1 scope but documented):

1. Make SyncEventBus defer nested events until the current event's
   subscriber chain completes. Effectively, a per-event queue with
   flush at the end of `publish`.
2. Use the AsyncEventBus in a single-threaded loop. The bus already
   supports `await`, so this should work.
3. Bypass the event bus entirely and call `agent.on_event` in a
   specific order: market_intel → strategy_gen → (collect signals) →
   risk_mgmt → (collect risk_checks) → execution. This is more
   invasive but explicit.

## Conclusion for Stage 1

- The 3-strategy config is verified to load correctly
- The strategies themselves produce signals on real data
- The execution path works in production (P0.6 smoke test)
- The backtester has a known infrastructure bug
- Stage 1 P0.7 (real round-trip during market hours) is still the
  authoritative test of the system

The backtester fix is tracked as a Stage 2 candidate under
"backtest reliability" but is NOT a Stage 1 blocker.
