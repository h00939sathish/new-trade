# Active Strategy Set — June 5, 2026

## Strategies in DEFAULT_CONFIG (src/config/strategy_config.py)

| Name | Type | Weight | Status | Cold-start |
|---|---|---|---|---|
| ema200_regime_gate | Filter | 0.0 | Enabled | 200 candles (~3.3h) |
| adx_regime_filter | Filter | 0.0 | Enabled | 14 candles (~15 min) |
| momentum | Trend | 0.40 | Active | 20 candles (~20 min) |
| sideways_reversion | Reversion | 0.35 | Active | 20 candles |
| vwap_reversion | Reversion | 0.25 | Active | 20 candles |

Disabled (in `__init__.py` ignore_list): `pca_statarb`, `ml_regime`, `stat_arb`.

## Cold-start math

All strategies and filters require warm-up. The longest is **EMA200 at 200 candles of 1-min OHLCV = 200 minutes ≈ 3.3 hours**.

NSE market hours: 9:15 - 15:30 IST (6h 15m = 375 minutes).

**First-signal-window opens at 9:15 + 200 min ≈ 12:35 IST.**

After that, all 3 active strategies + 2 filters are warm and can fire signals.

## Filter behavior

`ema200_regime_gate` and `adx_regime_filter` have weight=0 (they don't vote), but they block signals when their condition fails. The regime detection agent reads OHLCV and computes a regime (`trending_up`, `trending_down`, `mean_reverting`, `high_volatility`), and strategy_gen uses the regime to scale the active strategy weights via multipliers in [0.3, 2.0] (commit `a1adaa4`).

The two filters provide additional confirmation that a signal is consistent with the broader trend before it gets emitted. With 20-candle warm-up for the active strategies but 200-candle warm-up for EMA200, the first ~3 hours of every session will have active strategies warm but the EMA200 filter cold — those signals will be blocked by the cold-start check in EMA200Filter.

## Decided P2.1: re-enable filters

After P0.4 disabled them to prove execution path, Stage 3 P2.1 re-enables them. The rationale:

1. **EMA200 is a well-known regime indicator.** 200 days of 1-min data is enough; in 1-min intraday mode it's only 3.3h.
2. **ADX is fast** (15 min) and adds immediate value.
3. **Combined with the multiplier-based regime weight logic (commit `a1adaa4`)**, we get a layered filter system: regime detection from the regime agent + per-strategy multipliers + EMA200/ADX filters as final gates.
4. **We are now in a 30-day paper validation phase.** Blocking signals during the first 3 hours of each session is acceptable noise as long as signals can fire in the remaining 3 hours.

## What if the 3-hour signal window is too short?

The audit's note: in 6.25h NSE day, EMA200 cold-start eats 3.3h, leaving <3h of signal time. If 30-day paper data shows the system is signal-starved (e.g., < 1 trade per day on average), options:

1. Reduce EMA200 lookback to 100 (1.7h cold-start, 4.6h signal time)
2. Use a faster EMA (50 candles) with looser threshold
3. Compute EMA200 on 5-min candles (20 candles = 100 minutes = 1.7h cold-start)

These are deferred to Stage 3 P2.4 / P2.5 evaluation, not now.
