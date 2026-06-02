# Strategy Menu: @CodeTradingCafe → D:\projects\new trade
_Source: @CodeTradingCafe (channel ID UC2KjldN8pnX4FCNfVOlXUeA) visible titles + descriptions, May 2026 feed_

---

## 1. System-Level Recommendations

Priority: HIGH → LOW.

1. Add Hull Moving Average (HMA) as a first-class primitive. The codebase currently has raw-MA momentum and EMA MACD but no HMA. Two YouTube videos explicitly use HMA 16 cross HMA 64 as entry. Since HMA is just a weighted-WMA over WMA, it drops cleanly into `src/strategies/technical.py` as a shared helper and a strategy wrapper.

2. Split the current one-size-fits-all `MomentumStrategy` into two:
   - `ExponentialMomentumStrategy` — keeps current `short_window/long_window` as EWMA crossover (faster, mean-reversion-friendly).
   - `HullMomentumStrategy` — uses HMA crossover for the multi-timeframe setups described by the channel.
   Register both in `strategy_gen.py` with different default weights and cooldown behavior (HMA signals should filter less frequently).

3. Introduce `UnifiedTrendRegimeAgent` for multi-timeframe regime filtering. The channel's highest-return ideas use daily EMA 50/200 or linear-regression slope to block entries while the higher timeframe is bearish. In this repo, `StrategyGenAgent` already has a `_regime_instability_active` path driven by `MACRO_SENTIMENT` and frequent regime changes. Add a separate periodic evaluation (e.g., once per daily bar) that sets `_current_macro_multiplier` to 0.25–0.5 when EMA50 < EMA200, effectively turning the regime agent into a smoother trend veto that is independent of tick noise.

4. Use `_pending_signal_levels` with ATR-based dynamic SL/TP for all new strategies; don't hardcode 2%/5%. The channel uses `SL = ATR * 2` and `RR = 2:1`. The project already computes `atr` from `strategy features` in `src/agents/risk_mgmt.py`. Just make every strategy emit an `atr` feature and reuse the existing dynamic SL/TP logic.

5. Structural rules (90% of channel risk-control advice):
   - `regime_instability_active` → zero new entries when regime changes >3 in 10 minutes (already in code).
   - `signal_cooldown_seconds` → raise default to 180–300s for HMA regime strategies (crossovers on 4H often repaint on shorter TFs).
   - `sl_pct` lower-bound with 0.5% floor and 5% ceiling to avoid 0.2% spreads killing live setups (OK in backtest, lethal live).
   - `max_order_value` → reduce 10% when `pos[\"side\"] != 0` and ATR is elevated to keep per-trade loss within 1% of capital.
   - Auto-skip next N bars after exit before re-entry on the same side (anti-churn).

6. Add a regression-test kitchen-sink into tests:
   - Golden test using HMA 16 vs HMA 64 with frozen OHLCV array → fixed directional output (long/short/neutral).
   - Pinbar detection golden test with precomputed wick/body ratios.
   - `src/backtest/walk_forward.py` should exercise new strategies with rolling-window parameter search for `window`, `multiplier`, and `num_std` on 6-month data.

---

## 2. Strategy Catalog Aligned to Codebase

### Already Implemented / Directly Reusable

| ID | Strategy class | YT source | Match quality | Notes |
|---|---|---|---|---|
| `momentum` | `MomentumStrategy` | "Trend Filter Strategy", "A Simple Multi-Timeframe Strategy...", "HMA Strategy" | Good | Currently uses SMA. Swap to EMA for tick-based; add HMA variant. |
| `mean_reversion` | `MeanReversionStrategy` | "Bollinger Bands Mean Reversion (BTC)", "A Simple Trend Filter and a Candle to Beat Gold" | Good | Already in code. Add Bollinger mean-reversion with ATR-size gap filter. |
| `atr_breakout` | `ATRStrategy` | "A Simple Trend Filter and a Candle to Beat Gold" (ATR SL) | Excellent | Add `emit atr + change/(ATR+eps)` for dynamic sizing. |
| `bollinger` | `BollingerBandsStrategy` | "Tested a Bitcoin Strategy Using AI... Bollinger Bands mean reversion" | Good | Use only with daily trend filter. |
| `rsi` | `RSIStrategy` | "Multi-Timeframe Strategy" (RSI 14 confirmation) | Good | Validate with `rsi > 52` long filter, `rsi < 48` short filter. |

### To Implement (High ROI, Fast to Build)

| ID | Short definition | YT source | Where in repo |
|---|---|---|---|
| `hull_momentum` | HMA fast cross HMA slow; trend-slopey confirmation via daily EMA50/200. | Multi-Timeframe Strategy (HMA 16/64), BTC AI strategy | `src/strategies/technical.py` |
| `ema_trend_veto` | Not a trade signal by itself. If daily EMA 50 < EMA 200, set `_current_macro_multiplier *= 0.25`. | Multi-Timeframe Strategy daily trend filter, "Trend Filter Strategy" | `src/agents/strategy_gen.py` |
| `ml_regime` | `src/strategies/ml_regime.py` already exists (imported in `strategy_gen.py`). Needs daily-bar alignment. | "Genetic Programming" + regime switching concept | `src/strategies/ml_regime.py` |
| `pinbar` | Rejection candle + EMA trend filter + ATR SL + fixed 2:1 RR. | "Pinbar Trading", "Trend and Candle Trading" | `src/strategies/candle_patterns.py` (new file) or `technical.py` |
| `monte_carlo` | Salable "ready check" before promoting a candidate strategy. | "Stress Tested a 1700% Strategy..." | tests or `scripts/` |

---

## 3. Concrete Formula Adaptations

### 3a. Hull Moving Average (shared helper)

```
HMA(period):
  wma_half = WMA(period // 2)
  wma_full = WMA(period)
  raw = 2 * wma_half - wma_full
  return WMA(sqrt(period), raw_source)
```

`WMA(p, series[-p:]) = sum(i=1..p, (p-i+1)*series[-i]) / (p*(p+1)/2)`

Repository placement: add staticmethod `_hma(prices, period)` alongside `MACDStrategy._ema` in `src/strategies/technical.py`.

### 3b. Hull Crossover + Trend Filter (replaces/extends `momentum`)

```python
# candidate signal logic (inside a new HullMomentumStrategy)
if len(closes) < max(HMA_FAST, HMA_SLOW) + EMA200_bar:
    return None

hma_fast = _hma(closes, 16)
hma_slow = _hma(closes, 64)
trend_slope = _linreg_slope(closes, 200)                     # slope per bar
ema_daily = _ema(closes, 200) if use_daily else hma_slow    # proxy for daily if only intraday

entry = (
    hma_fast > hma_slow
    and trend_slope > 0
    and (use_daily_200_rule ? closes[-1] > ema_daily : True)
)
exit_on_cross_under = hma_fast < hma_slow
direction = "long" if entry else None
confidence = clamp(abs(hma_fast - hma_slow) / (atr + 1e-9) / 2.0, 0, 0.95)
features = {
    "hma_fast": hma_fast,
    "hma_slow": hma_slow,
    "trend_slope": trend_slope,
    "atr": atr,
}
```

Register in `_register_default_strategies` with weight 0.25 (standard) and 0.5 in trending regime.

### 3c. Daily Trend-Veto Agent (extends regime section)

Add a new entry in `_handle_system_state` (or a separate coroutine `_handle_daily_trend_event`):

```python
# pseudo
if daily_bar_event:
    daily_ema50 = _ema(daily_closes, 50)
    daily_ema200 = _ema(daily_closes, 200)
    if daily_ema50 < daily_ema200:
        self._current_macro_multiplier = 0.25   # allow 1-in-4 strength
    else:
        self._current_macro_multiplier = 1.0
```

This is safer than the existing ">3 regime changes in 10m" flag because it ignores noise and uses the dataset the system already ingests (4H/daily from `_candle_prices[instrument][interval]` when interval == `"day"`).

### 3d. Pinbar Rejection Candle

```python
# candle-based strategy; data_type = "candle", timeframe = "minute" (or 5min+)
body   = abs(close - open)
range_ = high - low + 1e-9
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low

pinbar_bull = (
    lower_wick >= 2.0 * body
    and upper_wick <= 0.3 * body
    and body <= 0.35 * range_
    and close > open                          # green candle preferred
    and direction == "long" only after ema50 > ema200
)
pinbar_bear = mirror image.

atr_14 = ...                                  # reuse existing ATR
sl = close - 2.0 * atr_14 if direction == "long" else close + 2.0 * atr_14
tp = close + 4.0 * atr_14 if direction == "long" else close - 4.0 * atr_14
confidence = clamp(lower_wick / (2.0 * atr_14 + 1e-9), 0, 0.95)
```

`features` must include `atr_14` so `_compute_dynamic_sl_tp` in `strategy_gen.py` can override static SL/TP if needed.

### 3e. ATR Embellishments (already partially implemented)

```
sl_pct_effective = (2 * ATR) / price
clamp(sl_pct, 0.005, 0.05)           # 0.5% floor, 5% ceiling
risk_per_trade = capital * 0.01
raw_qty = risk_per_trade / (price * sl_pct + eps)
max_qty  = (capital * 0.05) / price   # 5% nominal cap
take_profit_pct = sl_pct * 2.0        # 2:1 RR
```

Repository: tighten `_check_per_trade_risk` in `src/agents/risk_mgmt.py` (lines 259-299) to use the 0.5% floor and the 5:1 nominal cap consistently.

### 3f. Monte Carlo Readiness Check (new optional module)

```python
# requirements: trade list [(pnl, entry_bar, exit_bar), ...] from backtester
mc = MonteCarloArena(trades, n=5000)
mc.shuffle_equity()                      # permutation of trade order
mc.skip_test(skip_prob=0.15)             # randomly drop some trades
mc.bootstrap_confidence()
passes = (
    mc.robustness_score >= 0.70
    and mc.prob_drawdown_over(50, 0.55) < 0.5
    and mc.skip_confidence >= 0.80
)
# Only allow candidate -> live promotion when `passes`.
```

Place under `tests/` or `scripts/` and call it from `src/backtest/optimizer.py` before `_check_is_significant`.

---

## 4. Reference: Extracted Channel Strategy Nuggets → Repo Mapping

| Video title | Strategy nugget | Matches repo feature |
|---|---|---|
| A Simple Multi-Timeframe Strategy That Beat Buy & Hold | HMA 16 cross HMA 64; RSI 14 > 52; daily linear regression long-only filter | Momentum → replace SMA with HMA; add daily regime veto |
| Trend Filter Strategy | Moving-average trend filter | `regime_instability_active` equality-weights; extend with daily EMA50/200 |
| Trend and Candle Trading / Pinbar Trading | Bullish/bearish pinbar + ATR SL + 2:1 RR + auto-close after N bars | Implement `PinbarStrategy` in `technical.py`; reuse `_check_sl_tp` trailing |
| A Simple Trend Filter and a Candle to Beat Gold | Same pinbar setup with EMA 50/200 trend filter for Gold | Same file; add asset-agnostic `trend_filter` flag in config |
| I Stress Tested a 1700% Strategy... | Monte Carlo permutation + skip-trade + bootstrap → robustness score | `tests/robustness.py` → candidate → live gate |
| I Rebuilt the CoinQuant AI BTC Strategy in Python [Free Code] | HMA + RSI confirmation + LR filter, verified equity curve, commission-aware | Quantify commission per trade in `src/backtest/engine.py` slippage |
| Genetic Programming Trading Indicator Python | Evolve combinations of indicator expressions vs buy-and-hold | Extension: `src/agents/reflection_engine.py` can generate candidate formulas |
| I Tested a Bitcoin Strategy Using AI Without Writing a Single Line of Code | Bollinger lower-band long + equity fraction + single-position cap | `bollinger` strategy weight + `_check_instrument_risk` + existing position cap |

---

## 5. concrete Project Tasks (ordered)

### P0 — This Sprint (directly addresses the code you have)

1. Add `def _hma(prices, period)` helper in `src/strategies/technical.py`.
2. Add `HullMomentumStrategy` class (extends `Strategy`) in `src/strategies/technical.py`.
   - `data_type = "candle"`, `timeframe = "minute"`.
   - Requires `_candle_prices[instrument]["day"]` for daily HMA reference.
3. Update `_register_default_strategies` in `src/agents/strategy_gen.py` to also register `HullMomentumStrategy` with weight 0.22.
4. Publish a daily-trend-veto event from the OHLCV agent when interval == "day", consumed by `StrategyGenAgent._handle_system_state` (or a new `_on_daily_bar`) to suppress alpha on bearish daily regimes.
5. Add ATR feature emission to `ATRStrategy` and `BollingerBandsStrategy` (currently missing from Bollinger output).
6. Tighten SL/TP floor/ceiling in `_check_per_trade_risk` (`src/agents/risk_mgmt.py`, lines ~279-289) to protect live trading.
7. Add a "MONTE CARLO / ROBUSTNESS" alert subject in `src/agents/alert.py` so robustness results go to Telegram (channel emphasizes robustness scores).

### P1 — Next Sprint (robot upgrades)

8. Implement `PinbarStrategy` in a new file `src/strategies/candle_patterns.py` with `DataFrame-like` evaluator signature.
9. Make `MomentumStrategy` dual-mode: `mode="sma"` (existing) or `mode="ema"` to avoid SMA lag on tick data.
10. Add candidate → live promotion gate in `src/backtest/optimizer.py` that requires `robustness_score >= 0.70` from the Monte Carlo runner.
11. Expose `instrument_exposure` as a Telegram-quotable metric in `AlertAgent` (already shaped in `RiskCheckEvent`).
12. Refactor `src/agents/strategy_gen.py` voting section so each strategy's contribution is bounded to `[-0.5, +0.5]` pre-weight to prevent one very confident but flaky strategy from drowning the ensemble.

### P2 — Nice-to-Have / Learning Tasks (mentored by channel)

13. Build `scripts/monte_carlo_robustness.py` CLI: takes trade log pickle; outputs robustness score, drawdown probability, skip-test confidence.
14. Add a `src/strategies/genetic_programming.py` symbolic-expression evaluator (simple expression tree over prices/volumes/ATR/HMA ratios).
15. Add Telegram command `/status` that summarizes strategy weights, active regime, open positions, last N signals.

---

## 6. Registration Example (drop into `_register_default_strategies`)

```python
from src.strategies.technical import (
    ATRStrategy,
    BollingerBandsStrategy,
    HullMomentumStrategy,       # after adding it
    IchimokuStrategy,
    MACDStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    PinbarStrategy,             # after adding it
    RSIStrategy,
    VolumeStrategy,
)

def _register_default_strategies(self):
    pair = ("BTCUSDT", Exchange.COINDCX) if uses_crypto else ("RELIANCE", Exchange.NSE)
    defaults = [
        (HullMomentumStrategy(short=16, long=64), 0.25),
        (MomentumStrategy(short_window=5, long_window=20, threshold=0.02), 0.20),
        (MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.5), 0.25),
        (ATRStrategy(window=14, multiplier=2.0, threshold=0.01), 0.15),
        (BollingerBandsStrategy(window=20, num_std=2.0), 0.10),
        (RSIStrategy(window=14, oversold=30.0, overbought=70.0), 0.05),
    ]
    for strategy, weight in defaults:
        self.register_strategy(strategy, weight=weight)
```

---

## 7. Quick Checklist for Live Safety

- [ ] `sl_pct` floor at 0.5% (not 0.1%) — prevents spread-induced stop-outs.
- [ ] `sl_pct` ceiling at 5% — prevents absurdly wide stops.
- [ ] `take_profit_pct = sl_pct * 2.0` (exact 2:1 RR from channel).
- [ ] Auto-skip re-entry on same side for `cooldown_seconds` after exit (channel's post-exit discipline).
- [ ] Block new entries when daily EMA50 < EMA200 (regime veto).
- [ ] Candidate strategies emit only shadow signals (`_emit_candidate_signal` route); promotion requires MC pass.
- [ ] Telegram alert every time a candidate enters or exits live (`EVENT_TYPE.CANDIDATE_SIGNAL` already exists; just hook up AlertAgent).
