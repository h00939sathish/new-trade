# Strategy Research: 10-Item Roadmap
Project: `D:\projects\new trade`
Date: 2026-06-01

---

## 1. EMA200 Regime Filter

**Idea:** Use the price position relative to EMA200 as a top-level market-regime gate. Bullish when price > EMA200, bearish when price < EMA200, neutral near the average. This is a slower, cleaner trend filter than short-term EMA crossovers.

**Current state in codebase:**
- `MomentumStrategy` in `src/strategies/technical.py` uses simple SMA, not EMA.
- `MACDStrategy` has a static `_ema()` helper.
- `StrategyGenAgent` already has a `_get_15m_trend()` method using 20-period EMA.
- There is no dedicated daily/weekly EMA200 regime filter or macro multiplier derived from it.

**Implementation plan:**
- Add an `_ema200_trend(instrument)` helper in `src/strategies/technical.py` or `src/agents/strategy_gen.py`, using daily closes from `_candle_prices[instrument]["day"]`.
- In `StrategyGenAgent._handle_system_state()`, set `_current_macro_multiplier` based on EMA200:
  - `1.0` if price > EMA200 (bullish)
  - `0.25` if price < EMA200 (bearish)
  - `0.5` if within 1% of EMA200 (neutral/transition)
- This is safer and slower than the existing >3 regime-changes-in-10m guard, and complements it.

**Files to touch:**
- `src/strategies/technical.py`: add `_ema200_trend` staticmethod
- `src/agents/strategy_gen.py`: call it from `_handle_system_state` or a new `_on_daily_bar` handler

---

## 2. Cross-Sectional Momentum

**Idea:** Rank instruments by their recent performance relative to each other and go long the strongest / short the weakest. At any point you have a portfolio-level view, not just single-instrument signals.

**Current state in codebase:**
- The system is currently single-instrument: each strategy emits a signal for one instrument.
- `StrategyGenAgent` aggregates votes per instrument, not across instruments.
- No relative-strength or cross-sectional ranking logic.

**Implementation plan:**
- Add a new strategy class `CrossSectionalMomentumStrategy` in `src/strategies/technical.py`.
- It needs a rolling window of returns for all watchlist instruments.
- In `StrategyGenAgent`, maintain a `cross_sectional_scores` dict: `{instrument: momentum_score}` updated on each OHLCV tick.
- The strategy returns a `neutral` signal for weak instruments and a `long`/`short` signal for strong/weak ones, but the final decision should still go through ensemble vetting.
- Library-friendly approach: compute N-day returns for each instrument, rank them, go long top 1–2, short bottom 1–2, skip the rest.

**Files to touch:**
- `src/strategies/technical.py`: add `CrossSectionalMomentumStrategy`
- `src/agents/strategy_gen.py`: add `_update_cross_sectional_scores()` called from `_process_ohlcv`

---

## 3. Volatility Breakout

**Idea:** Enter when price expands beyond a recent volatility band (e.g., ATR multiple or Bollinger expansion). The core idea is “quiet periods predict explosive moves,” not just trending moves.

**Current state in codebase:**
- `ATRStrategy` exists and detects moves when `abs(change) / ATR` exceeds a threshold.
- `BollingerBandsStrategy` exists but triggers only when price leaves the bands.
- Neither explicitly models “low-volatility compression” followed by breakout.

**Implementation plan:**
- Refactor `ATRStrategy` or add `VolatilityBreakoutStrategy` that:
  - Computes `atr` over last N bars.
  - Computes `volatility_ratio = current_atr / average_atr(last M bars)`.
  - If `volatility_ratio < 0.6` for ~20 bars, then price move > `1.0 * ATR` in either direction triggers a signal.
  - Direction determined by the breakout direction, not the prior trend.
- This is distinct from the existing ATR strategy because it requires prior compression.

**Files to touch:**
- `src/strategies/technical.py`: add `VolatilityBreakoutStrategy`
- Optionally refactor `ATRStrategy` to share `_compute_atr` helper.

---

## 4. VWAP Pullback

**Idea:** In an intraday trend, buy pullbacks to VWAP (volume-weighted average price) and sell ripples away from VWAP. Only valid during the trading session.

**Current state in codebase:**
- `VolumeStrategy` uses volume spikes and price change but does not compute VWAP.
- No standard VWAP calculation or session anchoring.

**Implementation plan:**
- Add a new `VWAPPullbackStrategy` in `src/strategies/technical.py`.
  - For each trading session (reset at market open IST), accumulate `price * volume` and `volume`.
  - `vwap = cumulative_pv / cumulative_volume`.
  - If price deviates from VWAP by a threshold (e.g., `0.5%` to `1.5%`) in the direction of the trend, emit a pullback signal.
  - Use the existing 15-minute trend as trend filter: only long pullbacks in bullish trend, short ripples in bearish trend.
- Must respect `market_hours_only` guard so it does not compute across sessions.

**Files to touch:**
- `src/strategies/technical.py`: add `VWAPPullbackStrategy`
- `src/agents/strategy_gen.py`: ensure OHLCV feed includes volume (it already does) and session boundary detection.

---

## 5. Mean Reversion (SIDEWAYS only)

**Idea:** Only apply mean-reversion logic when the market is genuinely sideways (low trend strength, bounded range). In trending regimes, mean reversion fails.

**Current state in codebase:**
- `MeanReversionStrategy` already exists and uses z-score.
- `StrategyGenAgent._handle_system_state` already reduces mean-reversion weight in trending regimes, but there is no explicit “sideways” detection beyond the macro multiplier.

**Implementation plan:**
- Add a `SidewaysRegimeDetector`:
  - Use EMA slope flatness: `abs(ema20 - ema50) / ema50 < threshold` (e.g., 0.5%).
  - Or use ADX < 20 (average directional index) if available.
  - Or use recent high-low range relative to ATR.
- When `sideways == True`, boost `mean_reversion` and `bollinger` weights.
- When `sideways == False`, suppress them and prefer `momentum`/`atr_breakout`.
- This makes the existing `MeanReversionStrategy` regime-aware without changing its core math.

**Files to touch:**
- `src/strategies/technical.py`: add `_is_sideways_regime()` helper
- `src/agents/strategy_gen.py`: use it in `_handle_system_state`

---

## 6. Monte Carlo Robustness Gate

**Idea:** Before a strategy or a set of trades is trusted, run permutation/skip-trade/bootstrap tests on historical trade sequences to estimate drawdown probability and robustness score. Only allow live promotion if the score passes.

**Current state in codebase:**
- No Monte Carlo or bootstrap logic in `src/`.
- `tests/` has no robustness module.
- `StrategyGenAgent` has candidate strategies and a `_emit_candidate_signal` path, but no promotion gate.

**Implementation plan:**
- Add `tests/robustness.py` (or `src/backtest/robustness.py`).
- API:
  ```python
  class MonteCarloArena:
      def __init__(self, trades: list[dict], n=5000): ...
      def shuffle_equity(self): ...
      def skip_test(self, skip_prob=0.15): ...
      def bootstrap_confidence(self): ...
      @property
      def robustness_score(self): ...
      def prob_drawdown_over(self, threshold_pct, prob): ...
  ```
- Promotion rule: candidate -> live only if:
  - `robustness_score >= 0.70`
  - `prob_drawdown_over(50, 0.55) < 0.5`
  - `skip_confidence >= 0.80`
- Hook into `StrategyGenAgent` or a separate `BacktestOrchestrator` that consumes trade logs and emits a `CANDIDATE_PROMOTE` event.

**Files to touch:**
- New file: `src/backtest/robustness.py`
- Consume from: `src/agents/strategy_gen.py` or a new `promote_candidate()` flow.

---

## 7. Walk-Forward Validation

**Idea:** Instead of optimizing on the entire history and then testing out-of-sample once, use rolling windows: optimize on an in-sample window, test on the next out-of-sample window, then roll forward. This guards against overfitting much better than single train/test split.

**Current state in codebase:**
- No walk-forward or rolling-window optimizer exists.
- `src/backtest/` directory is not present.

**Implementation plan:**
- Add `src/backtest/walk_forward.py`.
- Core loop:
  ```python
  for window_start in range(0, total_bars - is_window - oos_window, step):
      is_data = bars[window_start : window_start + is_window]
      oos_data = bars[window_start + is_window : window_start + is_window + oos_window]
      best_params = optimize(strategy_class, is_data, param_grid)
      oos_metrics = evaluate(best_params, oos_data)
      results.append(oos_metrics)
  ```
- Use the existing strategy classes (Momentum, ATR, etc.) with parameter grids.
- Output: annualized return, max drawdown, Sharpe, win rate.

**Files to touch:**
- New directory: `src/backtest/`
- New file: `src/backtest/walk_forward.py`
- May reuse existing `Strategy classes` in `src/strategies/technical.py`.

---

## 8. Strategy Decay Detector

**Idea:** Track live performance metrics (win rate, average win/loss, Sharpe-like ratio) for each strategy over a rolling window. If performance degrades significantly vs. its own recent history, flag it for reoptimization or downweighting.

**Current state in codebase:**
- `ReflectionEngineAgent` exists and listens to `order.fill`.
- No explicit decay scoring or parameter retraining loop.

**Implementation plan:**
- Extend `ReflectionEngineAgent` or add a `StrategyHealthAgent`:
  - For each strategy, maintain a rolling deque of trade PnLs and durations.
  - Compute:
    - `recent_win_rate = wins / total_trades(last N)`
    - `recent_pnl_per_trade = sum(pnl) / N`
    - Compare to `baseline_win_rate` and `baseline_pnl_per_trade` from the first half of the window.
  - If `recent_win_rate < baseline_win_rate * 0.7`, flag as decaying.
  - Reduce strategy weight automatically or emit `STRATEGY_DECAY` event for human review.
- Store baseline stats in `state/strategy_health.yaml`.

**Files to touch:**
- `src/agents/reflection_engine.py`: extend to track per-strategy stats.
- New optional file: `src/agents/strategy_health.py` if separation is cleaner.

---

## 9. Risk-On / Risk-Off Allocator

**Idea:** Classify the current market state as risk-on or risk-off, then adjust portfolio exposure and strategy allocation accordingly. Risk-on = aggressive momentum, higher position size. Risk-off = defensive mean reversion, lower leverage, more cash.

**Current state in codebase:**
- `regime_detection` agent exists and emits system state.
- `StrategyGenAgent._handle_system_state` already changes weights by regime.
- No explicit portfolio-level allocator that varies total exposure or max position size per regime.

**Implementation plan:**
- Add `RiskAllocatorAgent` or extend `PortfolioOptAgent`:
  - Read regime from `SYSTEM_STATE` events.
  - Risk-on regimes (`trending_up`, `low_volatility`):
    - `max_position_pct = 0.10` of capital per trade
    - allow `momentum`, `atr_breakout` weights elevated
  - Risk-off regimes (`trending_down`, `high_volatility`, `regime_instability_active`):
    - `max_position_pct = 0.03`
    - suppress momentum / breakout, favor mean reversion or cash
- Emit `PORTFOLIO_ALLOCATION` event so `ExecutionAgent` and `RiskManagementAgent` can enforce it.

**Files to touch:**
- `src/agents/portfolio_opt.py` or new `src/agents/allocator.py`
- `src/schemas/events.py`: add `PORTFOLIO_ALLOCATION` event type if missing.

---

## 10. Regime-Switching Controller

**Idea:** Treat the market as having discrete regimes (trending, mean-reverting, high-volatility, choppy/instable), and switch strategy weights, risk limits, and position sizing smoothly when the regime changes. The transition itself should be gradual, not instantaneous, to avoid whipsaws.

**Current state in codebase:**
- `regime_detection` agent emits `SYSTEM_STATE` with a `regime` field.
- `StrategyGenAgent._handle_system_state` reacts to regime changes with hard weight jumps.
- There is a `_regime_instability_active` flag that flattens weights during rapid regime oscillation.
- No smooth blending between regimes.

**Implementation plan:**
- Replace the current hard-weight switch with an exponential moving average of regime probabilities:
  - `smoothed_regime = alpha * new_regime + (1 - alpha) * old_smoothed_regime`
  - Use `smoothed_regime` to interpolate weights between `trending_weights` and `mean_reverting_weights`.
- Add one more regime: `choppy` with very low weights for everything and a flat/neutral bias.
- Tie this to the EMA200 + ADX or `MACRO_SENTIMENT` inputs already ingested.
- This is the most systemic change: it affects weight updates in `_handle_system_state`, macro multiplier, and possibly risk ceilings in `RiskManagementAgent`.

**Files to touch:**
- `src/agents/strategy_gen.py`: refactor `_handle_system_state` to use smoothed regime blending.
- `src/agents/regime_detection.py`: ensure regime output is probabilistic, not just a single label.

---

## Summary Table

| # | Strategy | Current code support | Gap / New file |
|---|----------|----------------------|----------------|
| 1 | EMA200 Regime Filter | Partial (15m EMA20, MACD) | New helper + macro multiplier hook |
| 2 | Cross-Sectional Momentum | None | New strategy class + cross-instrument state |
| 3 | Volatility Breakout | Partial (ATR, Bollinger) | New strategy class with compression detection |
| 4 | VWAP Pullback | None | New strategy class + session anchoring |
| 5 | Mean Reversion (sideways) | Exists | Add sideways detector + regime-aware weights |
| 6 | Monte Carlo Robustness Gate | None | New module in `src/backtest/` |
| 7 | Walk-Forward Validation | None | New module in `src/backtest/` |
| 8 | Strategy Decay Detector | Partial (ReflectionEngine) | Extend reflection engine or new agent |
| 9 | Risk-On/Risk-Off Allocator | Partial (regime weights) | New allocator event + exposure rules |
| 10 | Regime-Switching Controller | Partial (hard switch + instability flag) | Smooth blending + higher-level regime model |

---

## Recommended Execution Order

**Phase A — Composable primitives (no new runtime risk)**
1. EMA200 Regime Filter
2. Volatility Breakout
3. Mean Reversion (sideways-only)

**Phase B — Portfolio-level controls**
4. VWAP Pullback
5. Cross-Sectional Momentum
6. Risk-On / Risk-Off Allocator

**Phase C — Validation and health**
7. Walk-Forward Validation
8. Monte Carlo Robustness Gate
9. Strategy Decay Detector

**Phase D — Systemic upgrade**
10. Regime-Switching Controller (after others are stable)
