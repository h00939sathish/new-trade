import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from src.agents.base import BaseAgent
from src.monitoring.latency_tracer import tracer
from src.risk.position_registry import position_registry
from src.schemas.events import Event, EventType, Exchange, SignalEvent
from src.strategies.base import Strategy
from src.strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from src.strategies.sideways_reversion import SidewaysReversionStrategy
from src.strategies.volatility_compression import VolatilityCompressionStrategy

__all__ = [
    "OpeningRangeBreakoutStrategy",
    "SidewaysReversionStrategy",
    "VolatilityCompressionStrategy",
    "Strategy",
    "StrategyGenAgent",
]

# Minimum seconds between signals for the same instrument (prevents overtrading)
_SIGNAL_COOLDOWN_SECONDS = 30.0


class StrategyGenAgent(BaseAgent):
    def __init__(self, event_store=None, config_path: str | None = None):
        super().__init__("strategy_gen", event_store=event_store)
        self._strategies: dict[str, Strategy] = {}
        self._strategy_weights: dict[str, float] = {}
        self._base_strategy_weights: dict[str, float] = {}
        self._candidate_strategies: dict[str, Strategy] = {}
        self._tick_prices: dict[str, deque[float]] = {}
        self._candle_prices: dict[str, dict[str, deque[float]]] = {}
        self._candle_volumes: dict[str, dict[str, deque[float]]] = {}
        self._candle_highs: dict[str, dict[str, deque[float]]] = {}
        self._candle_lows: dict[str, dict[str, deque[float]]] = {}
        self._candle_timestamps: dict[str, dict[str, deque[datetime]]] = {}
        self._config_path = config_path
        self._pending_signal_levels: dict[str, dict[str, float]] = {}
        self._last_tick_time: dict[str, datetime] = {}
        # Signal deduplication: track last emitted direction per instrument
        self._last_signal_direction: dict[str, str] = {}
        # Signal cooldown: track last signal emission time per instrument
        self._last_signal_time: dict[str, float] = {}
        self._current_macro_multiplier: float = 1.0
        self.threshold = 0.2
        self.short_threshold = 0.2
        self._signal_cooldown_seconds = 120.0
        self._regime_changes: list[float] = []
        self._regime_instability_active = False
        # Daily candle aggregation from minute data (for TSMOM and other daily strategies)
        self._daily_ohlcv: dict[
            str, dict
        ] = {}  # {instrument: {date, open, high, low, close, volume}}
        if self._config_path:
            try:
                from src.config.settings import settings

                self.threshold = settings.consensus_threshold
                self.short_threshold = settings.consensus_short_threshold
                self._signal_cooldown_seconds = settings.signal_cooldown_seconds
            except Exception:
                pass

    async def on_start(self) -> None:
        self.logger.info("Strategy Generation Agent initializing")
        self.subscribe_market_data()
        self.subscribe_system()
        self.subscribe(EventType.FILL)
        self.subscribe(EventType.MACRO_SENTIMENT)
        self._load_default_strategies()

    def register_strategy(self, strategy: "Strategy", weight: float = 1.0) -> None:
        self._strategies[strategy.name] = strategy
        self._strategy_weights[strategy.name] = weight
        self._base_strategy_weights[strategy.name] = weight
        self.logger.info("Registered strategy: %s (weight=%.1f)", strategy.name, weight)

    def register_candidate_strategy(self, strategy: "Strategy") -> None:
        self._candidate_strategies[strategy.name] = strategy
        self.logger.info("Registered CANDIDATE strategy for shadow trading: %s", strategy.name)

    async def on_event(self, event: Event) -> None:
        match event.event_type:
            case EventType.TICK:
                await self._process_tick(event)
            case EventType.OHLCV:
                await self._process_ohlcv(event)
            case EventType.FILL:
                await self._process_fill(event)
            case EventType.SYSTEM_STATE:
                self._handle_system_state(event)
            case EventType.SYSTEM_HEALTH:
                pass
            case EventType.MACRO_SENTIMENT:
                self._handle_macro_sentiment(event)

    def _handle_macro_sentiment(self, event: Event) -> None:
        data = event.data
        multiplier = data.get("composite_multiplier", 1.0)
        self._current_macro_multiplier = multiplier
        self.logger.info("Macro sentiment multiplier updated to: %.2f", multiplier)

    def _handle_system_state(self, event: Event) -> None:
        regime = event.data.get("regime")
        if not regime:
            return

        now = event.timestamp.timestamp()
        self._regime_changes.append(now)
        # Keep only changes within the last 10 minutes (600s)
        self._regime_changes = [t for t in self._regime_changes if now - t <= 600.0]

        # Debounce: if > 3 changes in 10 minutes, activate instability mode
        if len(self._regime_changes) > 3:
            if not self._regime_instability_active:
                self.logger.warning(
                    "Regime instability detected (>3 changes in 10m). Flattening weights and suppressing entries."
                )
                self._regime_instability_active = True
        else:
            if self._regime_instability_active:
                self.logger.info("Regime stabilized. Restoring regime-optimized weights.")
                self._regime_instability_active = False

        self.logger.info("Regime change detected in strategy_gen: %s", regime)

        # Explicit strategy group membership for regime-based weight allocation
        # FIX P0.7: regime weight logic was using absolute overrides (0.02-0.5)
        # which completely killed any strategy outside its preferred regime. This
        # is the root cause of "0 signals" in mean_reverting markets: trend
        # strategies got weight 0.02 and could never cross the consensus threshold.
        # Switched to multiplier-based scaling, matching the design in the old
        # trading_system repo (D:\projects\TRADE\trading_system\agents\signal_aggregation.py).
        # Multipliers are bounded [0.3, 2.0] so a strategy never collapses to 0.
        _TREND_STRATEGIES = {"momentum", "tsmom"}
        _BREAKOUT_STRATEGIES = {"orb", "vol_compression", "vol_breakout"}
        _REVERSION_STRATEGIES = {"sideways_reversion", "vwap_reversion"}
        _FILTER_STRATEGIES = {"ema200_regime_gate", "adx_regime_filter"}

        # Multipliers (not absolute weights) per regime. Format:
        #   regime -> {strategy_group -> multiplier}
        # Default multiplier is 1.0 (no change). A strategy's effective weight
        # is its base weight * multiplier, then the whole vector is renormalized.
        _MULTIPLIERS = {
            "trending_up": {"trend": 1.35, "breakout": 1.10, "reversion": 0.65},
            "trending_down": {"trend": 1.10, "breakout": 0.95, "reversion": 0.85},
            "mean_reverting": {"trend": 0.70, "breakout": 0.80, "reversion": 1.40},
            "high_volatility": {"trend": 0.55, "breakout": 1.15, "reversion": 0.50},
        }
        _GROUP_OF = {}
        for n in _TREND_STRATEGIES:
            _GROUP_OF[n] = "trend"
        for n in _BREAKOUT_STRATEGIES:
            _GROUP_OF[n] = "breakout"
        for n in _REVERSION_STRATEGIES:
            _GROUP_OF[n] = "reversion"
        for n in _FILTER_STRATEGIES:
            _GROUP_OF[n] = "filter"

        if self._regime_instability_active:
            # Flat equal weights during choppy regime oscillation
            n_active = max(len(self._strategy_weights) - len(_FILTER_STRATEGIES), 1)
            for name in list(self._strategy_weights.keys()):
                if name in _FILTER_STRATEGIES:
                    self._strategy_weights[name] = 0.0
                else:
                    self._strategy_weights[name] = 1.0 / n_active
        else:
            mults = _MULTIPLIERS.get(regime, {})
            for name in list(self._strategy_weights.keys()):
                if name in _FILTER_STRATEGIES:
                    # Filters always stay at 0 weight (non-voting)
                    self._strategy_weights[name] = 0.0
                    continue
                grp = _GROUP_OF.get(name)
                m = mults.get(grp, 1.0)
                # Bounded multiplier so nothing collapses to 0
                m = max(0.3, min(2.0, m))
                # Multiply the base weight (not the current weight)
                # by m, then renormalize the whole vector below.
                self._strategy_weights[name] = self._base_strategy_weights.get(name, 1.0) * m
        self._normalize_weights()

    async def _process_fill(self, event: Event) -> None:
        data = event.data
        instrument = data.get("instrument", "")
        data.get("side", "")
        data.get("fill_quantity", 0)
        data.get("fill_price", 0.0)
        if not instrument:
            return

        # Read from the shared position registry (updated by PortfolioAgent)
        pos = position_registry.get_position(instrument)
        new_qty = pos["quantity"]

        if new_qty == 0:
            # Position closed — clear signal deduplication so we can re-enter
            self._last_signal_direction.pop(instrument, None)
            self._last_signal_time.pop(instrument, None)
            self.logger.info("Position closed for %s — signal state reset", instrument)
        else:
            current_side = "long" if new_qty > 0 else "short"
            pending = self._pending_signal_levels.get(instrument, {})
            sl_pct = pending.get("stop_loss_pct", 0.02)
            tp_pct = pending.get("take_profit_pct", 0.05)

            avg_price = pos["avg_price"]
            if current_side == "long":
                sl = avg_price * (1.0 - sl_pct)
                tp = avg_price * (1.0 + tp_pct)
            else:
                sl = avg_price * (1.0 + sl_pct)
                tp = avg_price * (1.0 - tp_pct)

            await position_registry.set_sl_tp(
                instrument,
                stop_loss=sl,
                take_profit=tp,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
            )
            self.logger.info(
                "Position updated for %s: qty=%d, avg_price=%.2f, SL=%.2f, TP=%.2f",
                instrument,
                new_qty,
                avg_price,
                sl,
                tp,
            )

    async def _check_sl_tp(
        self, instrument: str, current_price: float, timestamp: datetime, exchange: Exchange
    ) -> None:
        pos = position_registry.get_position(instrument)
        if pos["quantity"] == 0:
            return

        is_trailing = True
        if pos["side"] == "long":
            if is_trailing:
                new_sl = current_price * (1.0 - pos["stop_loss_pct"])
                if new_sl > pos["stop_loss"]:
                    await position_registry.update_trailing_sl(instrument, new_sl)
                    self.logger.debug("Trailing SL updated for %s: %.2f", instrument, new_sl)
            if current_price <= pos["stop_loss"]:
                self.logger.warning(
                    "STOP LOSS hit for %s long at %.2f (SL: %.2f) — emitting exit signal",
                    instrument,
                    current_price,
                    pos["stop_loss"],
                )
                await self._emit_exit_signal(
                    instrument, current_price, "stop_loss", exchange, timestamp
                )
            elif current_price >= pos["take_profit"]:
                self.logger.warning(
                    "Take Profit hit for %s long position at %.2f (TP: %.2f)",
                    instrument,
                    current_price,
                    pos["take_profit"],
                )
                await self._emit_exit_signal(
                    instrument, current_price, "take_profit", exchange, timestamp
                )
        elif pos["side"] == "short":
            if is_trailing:
                new_sl = current_price * (1.0 + pos["stop_loss_pct"])
                if new_sl < pos["stop_loss"] or pos["stop_loss"] == 0.0:
                    await position_registry.update_trailing_sl(instrument, new_sl)
                    self.logger.debug("Trailing SL updated for %s: %.2f", instrument, new_sl)
            if current_price >= pos["stop_loss"]:
                self.logger.warning(
                    "STOP LOSS hit for %s short at %.2f (SL: %.2f) — emitting exit signal",
                    instrument,
                    current_price,
                    pos["stop_loss"],
                )
                await self._emit_exit_signal(
                    instrument, current_price, "stop_loss", exchange, timestamp
                )
            elif current_price <= pos["take_profit"]:
                self.logger.warning(
                    "Take Profit hit for %s short position at %.2f (TP: %.2f)",
                    instrument,
                    current_price,
                    pos["take_profit"],
                )
                await self._emit_exit_signal(
                    instrument, current_price, "take_profit", exchange, timestamp
                )

    async def _emit_exit_signal(
        self, instrument: str, price: float, reason: str, exchange: Exchange, timestamp: datetime
    ) -> None:
        # Clear signal deduplication state so we can re-enter after exit
        self._last_signal_direction.pop(instrument, None)
        self._last_signal_time.pop(instrument, None)
        signal = {
            "direction": "neutral",
            "confidence": 1.0,
            "price": price,
            "features": {"exit_reason": reason},
        }
        strategy_name = "consensus_ensemble"
        if len(self._strategies) == 1:
            strategy_name = list(self._strategies.keys())[0]
        await self._emit_signal(
            instrument, strategy_name, signal, exchange=exchange, timestamp=timestamp
        )

    async def _process_tick(self, event: Event) -> None:
        start_time = time.monotonic()
        instrument = event.data.get("instrument", "")
        exchange = Exchange(event.data.get("exchange", "NSE"))
        price = event.data.get("last_price")
        if price is None:
            return
        if instrument not in self._tick_prices:
            self._tick_prices[instrument] = deque(maxlen=500)
        self._tick_prices[instrument].append(float(price))

        await self._check_sl_tp(instrument, float(price), event.timestamp, exchange)

        depth = event.data.get("depth")
        bid = event.data.get("bid")
        ask = event.data.get("ask")

        # 1. Evaluate candidate strategies (shadow trading)
        for candidate in self._candidate_strategies.values():
            if getattr(candidate, "data_type", "any") in ("tick", "any"):
                prices_list = list(self._tick_prices[instrument])
                try:
                    signal = await candidate.evaluate(
                        instrument, prices_list, depth=depth, bid=bid, ask=ask
                    )
                except TypeError:
                    signal = await candidate.evaluate(instrument, prices_list)
                if signal is not None:
                    await self._emit_candidate_signal(
                        instrument, candidate.name, signal, exchange, event.timestamp
                    )

        # 2. Evaluate live strategies
        votes = []
        features_all = {}
        for strategy in self._strategies.values():
            if getattr(strategy, "data_type", "any") in ("tick", "any"):
                prices_list = list(self._tick_prices[instrument])
                try:
                    signal = await strategy.evaluate(
                        instrument, prices_list, depth=depth, bid=bid, ask=ask
                    )
                except TypeError:
                    signal = await strategy.evaluate(instrument, prices_list)
                if signal is not None:
                    direction = signal["direction"]
                    confidence = signal["confidence"]
                    dir_val = 1.0 if direction == "long" else -1.0 if direction == "short" else 0.0
                    weight = self._strategy_weights.get(strategy.name, 1.0)
                    vote = weight * dir_val * confidence
                    votes.append(vote)
                    features_all[strategy.name] = {
                        "direction": direction,
                        "confidence": confidence,
                        "vote": vote,
                        "features": signal.get("features", {}),
                    }

        if votes:
            net_signal = sum(votes) * self._current_macro_multiplier
            abs_net = abs(net_signal)
            direction = "long" if net_signal > 0 else "short"
            req_threshold = self.short_threshold if direction == "short" else self.threshold
            # DEBUG LOG
            if instrument in self._candle_prices and "1m" in self._candle_prices[instrument]:
                if len(self._candle_prices[instrument]["1m"]) % 500 == 0:
                    self.logger.info(
                        f"DEBUG {instrument} @ {event.timestamp}: net_signal={net_signal:.3f} abs={abs_net:.3f} thr={req_threshold} votes={votes}"
                    )

            if abs_net >= req_threshold:
                # Block new entries if regime is unstable
                if self._regime_instability_active:
                    return

                confidence = min(abs_net, 0.95)

                # Signal deduplication: skip if same direction as last signal
                if self._last_signal_direction.get(instrument) == direction:
                    return

                # Signal cooldown: skip if too recent
                now = event.timestamp.timestamp()
                last_time = self._last_signal_time.get(instrument, 0.0)
                if now - last_time < self._signal_cooldown_seconds:
                    return

                # Dynamic SL/TP based on ATR from strategy features
                sl_pct, tp_pct = self._compute_dynamic_sl_tp(features_all, float(price))
                self._pending_signal_levels[instrument] = {
                    "stop_loss_pct": sl_pct,
                    "take_profit_pct": tp_pct,
                }
                consolidated = {
                    "direction": direction,
                    "confidence": confidence,
                    "price": float(price),
                    "features": {"net_signal": net_signal, "votes": features_all},
                }
                strategy_name = "consensus_ensemble"
                if len(self._strategies) == 1:
                    strategy_name = list(self._strategies.keys())[0]

                self._last_signal_direction[instrument] = direction
                self._last_signal_time[instrument] = now
                tracer.record_trace(
                    event.metadata.correlation_id,
                    "strategy_gen",
                    (time.monotonic() - start_time) * 1000,
                )
                await self._emit_signal(
                    instrument,
                    strategy_name,
                    consolidated,
                    exchange=exchange,
                    timestamp=event.timestamp,
                    stop_loss_pct=sl_pct,
                    take_profit_pct=tp_pct,
                    correlation_id=event.metadata.correlation_id,
                )

    async def _process_ohlcv(self, event: Event) -> None:
        start_time = time.monotonic()
        instrument = event.data.get("instrument", "")
        exchange = Exchange(event.data.get("exchange", "NSE"))
        close = event.data.get("close")
        high = event.data.get("high", close)
        low = event.data.get("low", close)
        volume = event.data.get("volume", 0.0)
        interval = event.data.get("interval", "minute")
        if close is None:
            return
        if instrument not in self._candle_prices:
            self._candle_prices[instrument] = {}
        if interval not in self._candle_prices[instrument]:
            self._candle_prices[instrument][interval] = deque(maxlen=500)
        self._candle_prices[instrument][interval].append(float(close))

        if instrument not in self._candle_volumes:
            self._candle_volumes[instrument] = {}
        if interval not in self._candle_volumes[instrument]:
            self._candle_volumes[instrument][interval] = deque(maxlen=500)
        self._candle_volumes[instrument][interval].append(float(volume))

        # Store high/low for proper ATR calculation
        if instrument not in self._candle_highs:
            self._candle_highs[instrument] = {}
        if interval not in self._candle_highs[instrument]:
            self._candle_highs[instrument][interval] = deque(maxlen=500)
        self._candle_highs[instrument][interval].append(float(high) if high else float(close))

        if instrument not in self._candle_lows:
            self._candle_lows[instrument] = {}
        if interval not in self._candle_lows[instrument]:
            self._candle_lows[instrument][interval] = deque(maxlen=500)
        self._candle_lows[instrument][interval].append(float(low) if low else float(close))

        if instrument not in self._candle_timestamps:
            self._candle_timestamps[instrument] = {}
        if interval not in self._candle_timestamps[instrument]:
            self._candle_timestamps[instrument][interval] = deque(maxlen=500)
        self._candle_timestamps[instrument][interval].append(event.timestamp)

        # --- Daily candle aggregation from minute data ---
        if interval in ("minute", "1m"):
            from zoneinfo import ZoneInfo

            ist = ZoneInfo("Asia/Kolkata")
            ts_ist = (
                event.timestamp.astimezone(ist)
                if event.timestamp.tzinfo
                else event.timestamp.replace(tzinfo=ist)
            )
            today_str = ts_ist.strftime("%Y-%m-%d")
            c = float(close)
            h = float(high) if high else c
            l = float(low) if low else c
            v = float(volume)

            if instrument not in self._daily_ohlcv:
                self._daily_ohlcv[instrument] = {
                    "date": today_str,
                    "open": c,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                }
            else:
                daily = self._daily_ohlcv[instrument]
                if daily["date"] != today_str:
                    # New day — commit previous day's candle to the daily buffer
                    if "1d" not in self._candle_prices.get(instrument, {}):
                        if instrument not in self._candle_prices:
                            self._candle_prices[instrument] = {}
                        self._candle_prices[instrument]["1d"] = deque(maxlen=500)
                        self._candle_volumes[instrument]["1d"] = deque(maxlen=500)
                        self._candle_highs[instrument] = self._candle_highs.get(instrument, {})
                        self._candle_highs[instrument]["1d"] = self._candle_highs[instrument].get(
                            "1d", deque(maxlen=500)
                        )
                        self._candle_lows[instrument] = self._candle_lows.get(instrument, {})
                        self._candle_lows[instrument]["1d"] = self._candle_lows[instrument].get(
                            "1d", deque(maxlen=500)
                        )
                        self._candle_timestamps[instrument]["1d"] = deque(maxlen=500)
                    self._candle_prices[instrument]["1d"].append(daily["close"])
                    self._candle_volumes[instrument]["1d"].append(daily["volume"])
                    self._candle_highs[instrument]["1d"].append(daily["high"])
                    self._candle_lows[instrument]["1d"].append(daily["low"])
                    self._candle_timestamps[instrument]["1d"].append(event.timestamp)
                    # Reset for new day
                    self._daily_ohlcv[instrument] = {
                        "date": today_str,
                        "open": c,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": v,
                    }
                else:
                    # Same day — update running daily bar
                    daily["high"] = max(daily["high"], h)
                    daily["low"] = min(daily["low"], l)
                    daily["close"] = c
                    daily["volume"] += v

        await self._check_sl_tp(instrument, float(close), event.timestamp, exchange)

        # 1. Evaluate candidate strategies (shadow trading)
        for candidate in self._candidate_strategies.values():
            strategy_data_type = getattr(candidate, "data_type", "any")
            strategy_timeframe = getattr(candidate, "timeframe", "minute")
            norm_strat = (
                "1d"
                if strategy_timeframe in ("day", "1d", "daily")
                else "1m"
                if strategy_timeframe in ("minute", "1m")
                else strategy_timeframe
            )
            norm_event = (
                "1d"
                if interval in ("day", "1d", "daily")
                else "1m"
                if interval in ("minute", "1m")
                else interval
            )

            if strategy_data_type in ("candle", "any") and norm_strat == norm_event:
                prices_list = list(self._candle_prices[instrument][interval])
                volumes_list = list(self._candle_volumes[instrument][interval])
                highs_list = list(self._candle_highs.get(instrument, {}).get(interval, []))
                lows_list = list(self._candle_lows.get(instrument, {}).get(interval, []))
                timestamps_list = list(
                    self._candle_timestamps.get(instrument, {}).get(interval, [])
                )
                try:
                    signal = await candidate.evaluate(
                        instrument,
                        prices_list,
                        volumes=volumes_list,
                        highs=highs_list,
                        lows=lows_list,
                        timestamps=timestamps_list,
                    )
                except TypeError:
                    signal = await candidate.evaluate(
                        instrument,
                        prices_list,
                        volumes=volumes_list,
                        highs=highs_list,
                        lows=lows_list,
                    )
                if signal is not None:
                    await self._emit_candidate_signal(
                        instrument, candidate.name, signal, exchange, event.timestamp
                    )

        # 2. Evaluate live strategies
        votes = []
        features_all = {}
        for strategy in self._strategies.values():
            strategy_data_type = getattr(strategy, "data_type", "any")
            strategy_timeframe = getattr(strategy, "timeframe", "minute")

            norm_strat = (
                "1d"
                if strategy_timeframe in ("day", "1d", "daily")
                else "1m"
                if strategy_timeframe in ("minute", "1m")
                else strategy_timeframe
            )
            norm_event = (
                "1d"
                if interval in ("day", "1d", "daily")
                else "1m"
                if interval in ("minute", "1m")
                else interval
            )

            if strategy_data_type in ("candle", "any") and norm_strat == norm_event:
                prices_list = list(self._candle_prices[instrument][interval])
                volumes_list = list(self._candle_volumes[instrument][interval])
                highs_list = list(self._candle_highs.get(instrument, {}).get(interval, []))
                lows_list = list(self._candle_lows.get(instrument, {}).get(interval, []))
                timestamps_list = list(
                    self._candle_timestamps.get(instrument, {}).get(interval, [])
                )
                try:
                    signal = await strategy.evaluate(
                        instrument,
                        prices_list,
                        volumes=volumes_list,
                        highs=highs_list,
                        lows=lows_list,
                        timestamps=timestamps_list,
                    )
                except TypeError:
                    signal = await strategy.evaluate(
                        instrument,
                        prices_list,
                        volumes=volumes_list,
                        highs=highs_list,
                        lows=lows_list,
                    )
                if signal is not None:
                    direction = signal["direction"]
                    confidence = signal["confidence"]
                    dir_val = 1.0 if direction == "long" else -1.0 if direction == "short" else 0.0
                    weight = self._strategy_weights.get(strategy.name, 1.0)
                    vote = weight * dir_val * confidence
                    votes.append(vote)
                    features_all[strategy.name] = {
                        "direction": direction,
                        "confidence": confidence,
                        "vote": vote,
                        "features": signal.get("features", {}),
                    }

        if votes:
            net_signal = sum(votes) * self._current_macro_multiplier
            abs_net = abs(net_signal)
            direction = "long" if net_signal > 0 else "short"
            req_threshold = self.short_threshold if direction == "short" else self.threshold
            # DEBUG LOG
            if instrument in self._candle_prices and "1m" in self._candle_prices[instrument]:
                if len(self._candle_prices[instrument]["1m"]) % 500 == 0:
                    self.logger.info(
                        f"DEBUG {instrument} @ {event.timestamp}: net_signal={net_signal:.3f} abs={abs_net:.3f} thr={req_threshold} votes={votes}"
                    )

            if abs_net >= req_threshold:
                # Block new entries if regime is unstable
                if self._regime_instability_active:
                    return

                confidence = min(abs_net, 0.95)

                # Signal deduplication: skip if same direction as last signal
                if self._last_signal_direction.get(instrument) == direction:
                    return

                # Signal cooldown: skip if too recent
                now = event.timestamp.timestamp()
                last_time = self._last_signal_time.get(instrument, 0.0)
                if now - last_time < self._signal_cooldown_seconds:
                    return

                # Dynamic SL/TP based on ATR from strategy features
                sl_pct, tp_pct = self._compute_dynamic_sl_tp(features_all, float(close))
                self._pending_signal_levels[instrument] = {
                    "stop_loss_pct": sl_pct,
                    "take_profit_pct": tp_pct,
                }
                consolidated = {
                    "direction": direction,
                    "confidence": confidence,
                    "price": float(close),
                    "features": {"net_signal": net_signal, "votes": features_all},
                }
                strategy_name = "consensus_ensemble"
                if len(self._strategies) == 1:
                    strategy_name = list(self._strategies.keys())[0]

                self._last_signal_direction[instrument] = direction
                self._last_signal_time[instrument] = now
                tracer.record_trace(
                    event.metadata.correlation_id,
                    "strategy_gen",
                    (time.monotonic() - start_time) * 1000,
                )
                await self._emit_signal(
                    instrument,
                    strategy_name,
                    consolidated,
                    exchange=exchange,
                    timestamp=event.timestamp,
                    stop_loss_pct=sl_pct,
                    take_profit_pct=tp_pct,
                    correlation_id=event.metadata.correlation_id,
                )

    def _get_15m_trend(self, instrument: str) -> str:
        """Calculate 15-minute trend using 20-period EMA of 15m candles."""
        closes = self._candle_prices.get(instrument, {}).get("15minute", [])
        if not closes:
            closes = self._candle_prices.get(instrument, {}).get("15m", [])
        if not closes:
            closes = self._candle_prices.get(instrument, {}).get("15min", [])

        if len(closes) < 20:
            if len(closes) < 5:
                return "neutral"
            return "bullish" if closes[-1] > sum(closes) / len(closes) else "bearish"

        ema = closes[0]
        multiplier = 2 / (20 + 1)
        for c in list(closes)[1:]:
            ema = (c - ema) * multiplier + ema

        if closes[-1] > ema:
            return "bullish"
        elif closes[-1] < ema:
            return "bearish"
        return "neutral"

    async def _emit_signal(
        self,
        instrument: str,
        strategy: str,
        signal: dict[str, Any],
        exchange: Exchange = Exchange.NSE,
        timestamp: datetime | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        correlation_id: str | None = None,
    ) -> None:
        direction = signal.get("direction", "neutral")
        if direction in ("long", "short"):
            trend = self._get_15m_trend(instrument)
            if (direction == "long" and trend == "bearish") or (
                direction == "short" and trend == "bullish"
            ):
                self.logger.warning(
                    "Signal BLOCKED by 15m trend confirmation: %s %s (15m trend: %s)",
                    instrument,
                    direction,
                    trend,
                )
                return

        event = SignalEvent.create(
            instrument=instrument,
            strategy=strategy,
            direction=signal["direction"],
            confidence=signal["confidence"],
            price=signal.get("price"),
            features=signal.get("features"),
            exchange=exchange,
            producer=self.name,
            timestamp=timestamp,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            correlation_id=correlation_id,
        )
        self.logger.info(
            "Signal: %s %s %.2f%% from %s",
            instrument,
            signal["direction"],
            signal["confidence"] * 100,
            strategy,
        )
        try:
            from src.monitoring.metrics import system_metrics

            system_metrics.count_signal(strategy, signal["direction"])
        except Exception:
            pass
        await self.emit(event)

    async def _emit_candidate_signal(
        self,
        instrument: str,
        strategy: str,
        signal: dict[str, Any],
        exchange: Exchange,
        timestamp: datetime,
    ) -> None:
        """Emit a signal from a shadow candidate strategy. This is caught ONLY by the reflection engine."""
        event = SignalEvent.create(
            instrument=instrument,
            strategy=strategy,
            direction=signal["direction"],
            confidence=signal["confidence"],
            price=signal.get("price"),
            features=signal.get("features"),
            exchange=exchange,
            producer=self.name,
            timestamp=timestamp,
        )
        # Override event type to CANDIDATE_SIGNAL
        event.event_type = EventType.CANDIDATE_SIGNAL
        event.stream = f"signal.candidate.{strategy}.{instrument}"
        self.logger.debug(
            "Candidate Signal: %s %s %.2f%% from %s",
            instrument,
            signal["direction"],
            signal["confidence"] * 100,
            strategy,
        )
        await self.emit(event)

    def _normalize_weights(self) -> None:
        """Ensure strategy weights sum to exactly 1.0 for ensemble consistency."""
        total_w = sum(self._strategy_weights.values())
        if total_w > 0:
            for name in self._strategy_weights:
                self._strategy_weights[name] /= total_w

    def _load_default_strategies(self) -> None:
        """Initialize the core robust strategy portfolio from configuration."""
        from src.config.strategy_config import build_strategies_from_config, load_strategy_config

        cfg = load_strategy_config(self._config_path)
        strategies = build_strategies_from_config(cfg)
        for name, strategy in strategies.items():
            weight = cfg.get("strategies", {}).get(name, {}).get("weight", 1.0)
            self.register_strategy(strategy, weight=weight)

        self._normalize_weights()

    def _compute_dynamic_sl_tp(
        self,
        features_all: dict[str, dict[str, Any]],
        price: float,
    ) -> tuple[float, float]:
        """Compute dynamic SL/TP based on ATR from strategy features or overrides.

        Falls back to 2% SL / 4% TP if no ATR data available.
        Uses 2x ATR for SL and 3x ATR for TP (risk:reward = 1:1.5).
        """
        sl_override = None
        tp_override = None
        for _, strat_data in features_all.items():
            feat = strat_data.get("features", {})
            if "sl_pct_override" in feat and feat["sl_pct_override"] is not None:
                sl_override = feat["sl_pct_override"]
            if "tp_pct_override" in feat and feat["tp_pct_override"] is not None:
                tp_override = feat["tp_pct_override"]

        if sl_override is not None and tp_override is not None:
            return sl_override, tp_override

        atr = None
        for _, strat_data in features_all.items():
            feat = strat_data.get("features", {})
            if "atr" in feat and feat["atr"] is not None and feat["atr"] > 0:
                atr = feat["atr"]
                break

        if atr is not None and price > 0:
            sl_pct = min(max((2.0 * atr) / price, 0.005), 0.05)  # Clamp: 0.5%-5%
            tp_pct = min(max((3.0 * atr) / price, 0.01), 0.10)  # Clamp: 1%-10%
        else:
            sl_pct = 0.02
            tp_pct = 0.04

        final_sl = sl_override if sl_override is not None else sl_pct
        final_tp = tp_override if tp_override is not None else tp_pct

        return final_sl, final_tp

    async def on_stop(self) -> None:
        self.logger.info("Strategy Generation Agent stopping")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update(
            {
                "strategies": list(self._strategies.keys()),
                "instruments_tracked": len(self._tick_prices) + len(self._candle_prices),
                "positions_tracked": len(position_registry.get_all_positions()),
                "cooldown_active": [
                    k
                    for k, v in self._last_signal_time.items()
                    if datetime.now(UTC).timestamp() - v < _SIGNAL_COOLDOWN_SECONDS
                ],
            }
        )
        return base
