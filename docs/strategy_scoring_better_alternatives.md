# Strategy Scoring & Better Alternatives
Project: `D:\projects\new trade`
Date: 2026-06-01
Reference: `docs/strategy_research_10.md`

---

## Scoring Rubric

Each strategy is scored 1-10 on:
- **A** Fit for NSE large-cap equities (RELIANCE, TCS, INFY, HDFCBANK)
- **B** Fit for current codebase (reuse vs greenfield)
- **C** Risk-adjusted profitability potential
- **D** Implementation effort (lower is easier; 10 = trivial)
- **E** Robustness to overfitting / regime change
- **Overall** weighted average

Weights: A=25%, B=15%, C=25%, D=15% (inverted so easy = better), E=20%

---

## Scores

| # | Strategy | A | B | C | D | E | Overall |
|---|----------|---|---|---|---|---|---------|
| 1 | EMA200 Regime Filter | 9 | 8 | 6 | 8 | 7 | 7.65 |
| 2 | Cross-Sectional Momentum | 8 | 3 | 7 | 4 | 6 | 5.75 |
| 3 | Volatility Breakout | 8 | 7 | 7 | 7 | 7 | 7.20 |
| 4 | VWAP Pullback | 9 | 4 | 8 | 3 | 7 | 6.35 |
| 5 | Mean Reversion (Sideways) | 8 | 9 | 7 | 9 | 6 | 7.65 |
| 6 | Monte Carlo Gate | 7 | 4 | 8 | 3 | 9 | 6.40 |
| 7 | Walk-Forward Validation | 7 | 3 | 8 | 3 | 9 | 6.10 |
| 8 | Strategy Decay Detector | 8 | 6 | 7 | 6 | 8 | 7.15 |
| 9 | Risk-On/Risk-Off Allocator | 8 | 5 | 7 | 5 | 8 | 6.80 |
| 10 | Regime-Switching Controller | 8 | 5 | 7 | 4 | 8 | 6.55 |

### What the scores mean

- **EMA200 Regime Filter (7.65):** Very strong fit for your universe. Large-caps respond well to trend filtering. Easy to wire into `strategy_gen.py`. Biggest value is as a *controller*, not a standalone signal.
- **Cross-Sectional Momentum (5.75):** Powerful in equities generally, but your current architecture is single-instrument. Retrofitting cross-instrument ranking is non-trivial.
- **Volatility Breakout (7.20):** Natural extension of your existing ATR logic. Good for NSE mid-large caps that have volatility contraction/expansion cycles.
- **VWAP Pullback (6.35):** Excellent for intraday, but your data feed is 60s polling from Yahoo Finance; VWAP precision at that granularity is weak. Better suited to tick-level data.
- **Mean Reversion Sideways (7.65):** Highest reuse value. Class already exists. Adding sideways detection is straightforward. Best paired with a trend filter.
- **Monte Carlo Gate (6.40):** Useful but not a strategy; it’s a risk/validation tool. High long-term value, low immediate P&L impact.
- **Walk-Forward Validation (6.10):** Also a tool, not a strategy. Important for robustness, but no direct edge.
- **Strategy Decay Detector (7.15):** Practical for live survival. Fits naturally with your existing `reflection_engine`. Medium implementation effort.
- **Risk-On/Risk-Off Allocator (6.80):** Useful portfolio-level control. Medium effort because it touches multiple agents.
- **Regime-Switching Controller (6.55):** Conceptually strong but complex. Your current hard switch + instability flag is already decent. Smooth blending is a refinement, not a breakthrough.

### Top 3 by score
1. Mean Reversion (Sideways) — 7.65
2. EMA200 Regime Filter — 7.65
3. Volatility Breakout — 7.20

### Biggest gaps vs. current code
- Cross-Sectional Momentum and VWAP Pullback require data/architecture changes.
- Monte Carlo and Walk-Forward are backtest-only upgrades.
- The regime/allocator items are controller-layer upgrades.

---

## Better Alternatives for Your Use Case

Your constraint set is important:
- NSE large-cap equities (RELIANCE, TCS, INFY, HDFCBANK)
- 60-second polling, not tick data
- Paper trading first, ₹10,00,000 capital
- Hard risk limits: ₹5,000 max daily loss, 5% max drawdown
- Existing strategy primitives: momentum, mean reversion, ATR, Bollinger, RSI, MACD, Ichimoku, volume
- Telegram alerts, in-hours-only trading

### A. Opening-Range Breakout (ORB)

**Why better for you:**
- NSE large-caps tend to establish a 15-minute opening range (09:15–09:30 IST) and then trend.
- Works with 1-minute or 5-minute bars; no tick data required.
- Simple to implement, easy to backtest, low parameter risk.

**Formula:**
- OR_high = high of first 15 minutes
- OR_low = low of first 15 minutes
- If price closes above OR_high + 0.1% buffer → long
- If price closes below OR_low - 0.1% buffer → short
- SL = OR_low (long) or OR_high (short)
- TP = 1.5× range width

**Fit score:** 9/10
- A: 9 (proven NSE intraday)
- B: 5 (new file, but reuses `_process_ohlcv`)
- C: 7 (works well in trending days, choppy days it whipsaws)
- D: 8 (simple)
- E: 7 (needs time-of-day filter)

**Improvement vs. your list:**
- More concrete than “volatility breakout”
- Session-anchored, so it doesn’t leak across days
- Directly maps to your in-hours-only constraint

### B. Keltner Channel Pullback

**Why better for you:**
- Combines trend (EMA) with volatility envelope (ATR-based channel).
- Pullback entries inside the channel reduce chasing.
- Analogous to VWAP pullback but works with 60s bars because it uses ATR, not volume-weighted ticks.

**Formula:**
- Middle = EMA20
- Upper = EMA20 + 2×ATR
- Lower = EMA20 - 2×ATR
- In bullish regime (price > EMA50): wait for price to touch lower band → long
- SL = lower band - 0.5×ATR
- TP = middle band

**Fit score:** 8.5/10
- A: 8 (works on NSE large-caps)
- B: 8 (extends existing ATR and momentum logic)
- C: 8
- D: 8
- E: 8

**Improvement vs. your list:**
- More robust than Bollinger mean reversion because it uses ATR, not std-dev, which is less sensitive to gap days.
- Replaces the weaker part of your current `bollinger` strategy with a trend-aware version.

### C. SuperTrend (Parabolic SAR variant)

**Why better for you:**
- Extremely popular on Indian retail trading platforms (TradingView, Zerodha).
- Produces very clean trend-following signals on 5-minute and 15-minute charts of large-caps.
- Low parameter risk (default ATR multiplier = 3.0).

**Formula:**
- SAR(t) = SAR(t-1) + AF × (EP - SAR(t-1))
- Where AF = acceleration factor (starts 0.02, increases to 0.2), EP = extreme price
- Long when price > SAR, short when price < SAR
- SL/TP can be set at SAR itself

**Fit score:** 8.5/10
- A: 9 (widely used on NSE)
- B: 7 (new helper but reuses ATR)
- C: 7 (good in trending markets, whipsaws in sideways)
- D: 7
- E: 7

**Improvement vs. your list:**
- More trend-following robust than HMA crossover (fewer whipsaws).
- Self-adjusting stop distance via ATR.
- Easy to combine with your existing regime filter.

### D. Donchian Channel Breakout

**Why better for you:**
- 20-day high breakout is one of the most robust single-factor trend strategies ever published (Turtle Trading rules).
- Works well on NSE large-caps because they trend in bursts.
- Minimal parameters: just channel length.

**Formula:**
- long entry: price >= max(high, last 20 days)
- short entry: price <= min(low, last 20 days)
- SL = 2×ATR from entry
- Exit: reverse signal or 10-day trailing exit

**Fit score:** 8/10
- A: 9 (classic turtle, proven globally and on NSE)
- B: 7 (reuses highs/lows already stored)
- C: 7 (captures trend bursts)
- D: 9 (trivial)
- E: 8 (very robust to parameter changes)

**Improvement vs. your list:**
- Simpler and more robust than HMA or momentum crossover.
- Works on daily bars, so less noise than intraday indicators.
- Directly complements your existing ATR strategy.

### E. Volume-Price Confirmation (existing VolumeStrategy upgrade)

**Why better for you:**
- Your `VolumeStrategy` already captures volume spikes, but it ignores price *context* (e.g., is the spike happening at resistance?).
- Adding price-level confirmation turns it from a noisy filter into a high-quality entry trigger.

**Formula:**
- Volume spike: current volume > 1.5× 20-period average
- AND price is breaking a 20-period high/low
- AND candle is net bullish/bearish (close > open or vice versa)
- THEN signal

**Fit score:** 8/10
- A: 8 (works well on NSE event days)
- B: 9 (extends `VolumeStrategy` with minor changes)
- C: 7
- D: 8
- E: 7

---

## Recommendations

**Drop from priority list:**
- Cross-Sectional Momentum: too much architectural change for your current single-instrument design.
- Walk-Forward Validation: keep as a backtesting hygiene task, not a live strategy.
- Monte Carlo Gate: same — useful, but not a signal source.

**Promote to shortlist:**
1. Mean Reversion (Sideways) — already 90% there
2. ORB (Opening-Range Breakout) — most actionable NSE-specific alpha
3. Keltner Channel Pullback — best bridge between trend and mean reversion
4. SuperTrend — easiest to deploy, already popular in your target market
5. EMA200 Regime Filter — already mostly implemented

**Replace weaker items:**
- Volatility Breakout → Keltner Channel Pullback (higher win rate, lower whipsaw)
- VWAP Pullback → ORB (same intraday edge, simpler data requirements)
- Risk-On/Risk-Off Allocator → keep, but treat as overlay, not a strategy
- Regime-Switching Controller → retire for now; hard switch + EMA200 filter is sufficient

---

## Next Step

If you want, I can implement **Opening-Range Breakout** and **Keltner Channel Pullback** first, since they:
- map cleanly to your OHLCV feed,
- require no new data sources,
- are proven on NSE large-caps,
- and can be registered in `strategy_gen.py` alongside your existing strategies.
