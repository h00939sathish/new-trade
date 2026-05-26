import math
import time
from collections import deque
from datetime import datetime
from typing import Any, Literal

from src.agents.base import BaseAgent
from src.risk.position_registry import position_registry
from src.schemas.events import Event, EventType, Exchange, SignalEvent
from src.strategies.base import Strategy
from src.strategies.technical import (
    ATRStrategy,
    BollingerBandsStrategy,
    IchimokuStrategy,
    MACDStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    RSIStrategy,
    VolumeStrategy,
)

# Minimum seconds between signals for the same instrument (prevents overtrading)
_SIGNAL_COOLDOWN_SECONDS = 30.0


class StrategyGenAgent(BaseAgent):
    def __init__(self, event_store=None, config_path: str | None = None):
        super().__init__("strategy_gen", event_store=event_store)
        self._strategies: dict[str, Strategy] = {}
        self._strategy_weights: dict[str, float] = {}
        self._tick_prices: dict[str, deque[float]] = {}
        self._candle_prices: dict[str, dict[str, deque[float]]] = {}
        self._candle_volumes: dict[str, dict[str, deque[float]]] = {}
        self._candle_highs: dict[str, dict[str, deque[float]]] = {}
        self._candle_lows: dict[str, dict[str, deque[float]]] = {}
        self._config_path = config_path
        self._pending_signal_levels: dict[str, dict[str, float]] = {}
        self._last_tick_time: dict[str, datetime] = {}
        # Signal deduplication: track last emitted direction per instrument
        self._last_signal_direction: dict[str, str] = {}
        # Signal cooldown: track last signal emission time per instrument
        self._last_signal_time: dict[str, float] = {}
        self.threshold = 0.3  # Increased from 0.1 to reduce noise
        if self._config_path:
            try:
                from src.config.strategy_config import load_strategy_config
                cfg = load_strategy_config(self._config_path)
                self.threshold = cfg.get("consensus_threshold", 0.3)
            except Exception:
                pass

    async def on_start(self) -> None:
        self.logger.info("Strategy Generation Agent initializing")
        self.subscribe_market_data()
        self.subscribe_system()
        self.subscribe(EventType.FILL)
        self._register_default_strategies()

    def register_strategy(self, strategy: "Strategy", weight: float = 1.0) -> None:
        self._strategies[strategy.name] = strategy
        self._strategy_weights[strategy.name] = weight
        self.logger.info("Registered strategy: %s (weight=%.1f)", strategy.name, weight)

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

    def _handle_system_state(self, event: Event) -> None:
        regime = event.data.get("regime")
        if not regime:
            return
        self.logger.info("Regime change detected in strategy_gen: %s", regime)
        for name in list(self._strategy_weights.keys()):
            if regime in ("trending_up", "trending_down"):
                if "momentum" in name or "breakout" in name:
                    self._strategy_weights[name] = 0.5
                elif "reversion" in name or "rsi" in name or "bollinger" in name:
                    self._strategy_weights[name] = 0.05
            elif regime == "mean_reverting":
                if "momentum" in name or "breakout" in name:
                    self._strategy_weights[name] = 0.05
                elif "reversion" in name or "rsi" in name or "bollinger" in name:
                    self._strategy_weights[name] = 0.5
            elif regime == "high_volatility":
                self._strategy_weights[name] = 0.02

    async def _process_fill(self, event: Event) -> None:
        data = event.data
        instrument = data.get("instrument", "")
        side = data.get("side", "")
        fill_qty = data.get("fill_quantity", 0)
        fill_price = data.get("fill_price", 0.0)
        if not instrument:
            return

        # Update the shared position registry
        pos = position_registry.update_from_fill(instrument, side, fill_qty, fill_price)
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

            position_registry.set_sl_tp(
                instrument, stop_loss=sl, take_profit=tp,
                stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
            )
            self.logger.info(
                "Position updated for %s: qty=%d, avg_price=%.2f, SL=%.2f, TP=%.2f",
                instrument, new_qty, avg_price, sl, tp,
            )

    async def _check_sl_tp(self, instrument: str, current_price: float, timestamp: datetime, exchange: Exchange) -> None:
        pos = position_registry.get_position(instrument)
        if pos["quantity"] == 0:
            return

        is_trailing = True
        if pos["side"] == "long":
            if is_trailing:
                new_sl = current_price * (1.0 - pos["stop_loss_pct"])
                if new_sl > pos["stop_loss"]:
                    position_registry.update_trailing_sl(instrument, new_sl)
                    self.logger.debug("Trailing SL updated for %s: %.2f", instrument, new_sl)
            if current_price <= pos["stop_loss"]:
                self.logger.warning("Stop Loss hit for %s long position at %.2f (SL: %.2f)", instrument, current_price, pos["stop_loss"])
                await self._emit_exit_signal(instrument, current_price, "stop_loss", exchange, timestamp)
            elif current_price >= pos["take_profit"]:
                self.logger.warning("Take Profit hit for %s long position at %.2f (TP: %.2f)", instrument, current_price, pos["take_profit"])
                await self._emit_exit_signal(instrument, current_price, "take_profit", exchange, timestamp)
        elif pos["side"] == "short":
            if is_trailing:
                new_sl = current_price * (1.0 + pos["stop_loss_pct"])
                if new_sl < pos["stop_loss"] or pos["stop_loss"] == 0.0:
                    position_registry.update_trailing_sl(instrument, new_sl)
                    self.logger.debug("Trailing SL updated for %s: %.2f", instrument, new_sl)
            if current_price >= pos["stop_loss"]:
                self.logger.warning("Stop Loss hit for %s short position at %.2f (SL: %.2f)", instrument, current_price, pos["stop_loss"])
                await self._emit_exit_signal(instrument, current_price, "stop_loss", exchange, timestamp)
            elif current_price <= pos["take_profit"]:
                self.logger.warning("Take Profit hit for %s short position at %.2f (TP: %.2f)", instrument, current_price, pos["take_profit"])
                await self._emit_exit_signal(instrument, current_price, "take_profit", exchange, timestamp)

    async def _emit_exit_signal(self, instrument: str, price: float, reason: str, exchange: Exchange, timestamp: datetime) -> None:
        # Clear signal deduplication state so we can re-enter after exit
        self._last_signal_direction.pop(instrument, None)
        self._last_signal_time.pop(instrument, None)
        signal = {
            "direction": "neutral",
            "confidence": 1.0,
            "price": price,
            "features": {"exit_reason": reason}
        }
        strategy_name = "consensus_ensemble"
        if len(self._strategies) == 1:
            strategy_name = list(self._strategies.keys())[0]
        await self._emit_signal(instrument, strategy_name, signal, exchange=exchange, timestamp=timestamp)

    async def _process_tick(self, event: Event) -> None:
        instrument = event.data.get("instrument", "")
        exchange = Exchange(event.data.get("exchange", "NSE"))
        price = event.data.get("last_price")
        if price is None:
            return
        if instrument not in self._tick_prices:
            self._tick_prices[instrument] = deque(maxlen=500)
        self._tick_prices[instrument].append(float(price))

        await self._check_sl_tp(instrument, float(price), event.timestamp, exchange)

        votes = []
        features_all = {}
        for strategy in self._strategies.values():
            if getattr(strategy, "data_type", "any") in ("tick", "any"):
                prices_list = list(self._tick_prices[instrument])
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
                        "features": signal.get("features", {})
                    }

        if votes:
            net_signal = sum(votes)
            abs_net = abs(net_signal)
            if abs_net >= self.threshold:
                direction = "long" if net_signal > 0 else "short"
                confidence = min(abs_net, 0.95)

                # Signal deduplication: skip if same direction as last signal
                if self._last_signal_direction.get(instrument) == direction:
                    return

                # Signal cooldown: skip if too recent
                now = time.monotonic()
                last_time = self._last_signal_time.get(instrument, 0.0)
                if now - last_time < _SIGNAL_COOLDOWN_SECONDS:
                    return

                # Dynamic SL/TP based on ATR from strategy features
                sl_pct, tp_pct = self._compute_dynamic_sl_tp(features_all, float(price))
                self._pending_signal_levels[instrument] = {
                    "stop_loss_pct": sl_pct,
                    "take_profit_pct": tp_pct
                }
                consolidated = {
                    "direction": direction,
                    "confidence": confidence,
                    "price": float(price),
                    "features": {
                        "net_signal": net_signal,
                        "votes": features_all
                    }
                }
                strategy_name = "consensus_ensemble"
                if len(self._strategies) == 1:
                    strategy_name = list(self._strategies.keys())[0]

                self._last_signal_direction[instrument] = direction
                self._last_signal_time[instrument] = now
                await self._emit_signal(instrument, strategy_name, consolidated, exchange=exchange, timestamp=event.timestamp,
                                        stop_loss_pct=sl_pct, take_profit_pct=tp_pct)

    async def _process_ohlcv(self, event: Event) -> None:
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

        await self._check_sl_tp(instrument, float(close), event.timestamp, exchange)

        votes = []
        features_all = {}
        for strategy in self._strategies.values():
            strategy_data_type = getattr(strategy, "data_type", "any")
            strategy_timeframe = getattr(strategy, "timeframe", "minute")

            norm_strat = strategy_timeframe.replace("minute", "m").replace("1m", "minute")
            norm_event = interval.replace("minute", "m").replace("1m", "minute")

            if strategy_data_type in ("candle", "any") and (norm_strat == norm_event or strategy_timeframe == interval):
                prices_list = list(self._candle_prices[instrument][interval])
                volumes_list = list(self._candle_volumes[instrument][interval])
                highs_list = list(self._candle_highs.get(instrument, {}).get(interval, []))
                lows_list = list(self._candle_lows.get(instrument, {}).get(interval, []))
                signal = await strategy.evaluate(
                    instrument, prices_list, volumes=volumes_list,
                    highs=highs_list, lows=lows_list,
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
                        "features": signal.get("features", {})
                    }

        if votes:
            net_signal = sum(votes)
            abs_net = abs(net_signal)
            if abs_net >= self.threshold:
                direction = "long" if net_signal > 0 else "short"
                confidence = min(abs_net, 0.95)

                # Signal deduplication: skip if same direction as last signal
                if self._last_signal_direction.get(instrument) == direction:
                    return

                # Signal cooldown: skip if too recent
                now = time.monotonic()
                last_time = self._last_signal_time.get(instrument, 0.0)
                if now - last_time < _SIGNAL_COOLDOWN_SECONDS:
                    return

                # Dynamic SL/TP based on ATR from strategy features
                sl_pct, tp_pct = self._compute_dynamic_sl_tp(features_all, float(close))
                self._pending_signal_levels[instrument] = {
                    "stop_loss_pct": sl_pct,
                    "take_profit_pct": tp_pct
                }
                consolidated = {
                    "direction": direction,
                    "confidence": confidence,
                    "price": float(close),
                    "features": {
                        "net_signal": net_signal,
                        "votes": features_all
                    }
                }
                strategy_name = "consensus_ensemble"
                if len(self._strategies) == 1:
                    strategy_name = list(self._strategies.keys())[0]

                self._last_signal_direction[instrument] = direction
                self._last_signal_time[instrument] = now
                await self._emit_signal(instrument, strategy_name, consolidated, exchange=exchange, timestamp=event.timestamp,
                                        stop_loss_pct=sl_pct, take_profit_pct=tp_pct)

    async def _emit_signal(
        self,
        instrument: str,
        strategy: str,
        signal: dict[str, Any],
        exchange: Exchange = Exchange.NSE,
        timestamp: datetime | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ) -> None:
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
        )
        self.logger.info(
            "Signal: %s %s %.2f%% from %s",
            instrument, signal["direction"], signal["confidence"] * 100, strategy,
        )
        try:
            from src.monitoring.metrics import system_metrics
            system_metrics.count_signal(strategy, signal["direction"])
        except Exception:
            pass
        await self.emit(event)

    def _register_default_strategies(self) -> None:
        from src.config.strategy_config import build_strategies_from_config, load_strategy_config
        cfg = load_strategy_config(self._config_path)
        strategies = build_strategies_from_config(cfg)
        for name, strategy in strategies.items():
            weight = cfg.get("strategies", {}).get(name, {}).get("weight", 1.0)
            self.register_strategy(strategy, weight=weight)

    def _compute_dynamic_sl_tp(
        self,
        features_all: dict[str, dict[str, Any]],
        price: float,
    ) -> tuple[float, float]:
        """Compute dynamic SL/TP based on ATR from strategy features.

        Falls back to 2% SL / 4% TP if no ATR data available.
        Uses 2x ATR for SL and 3x ATR for TP (risk:reward = 1:1.5).
        """
        atr = None
        for _, strat_data in features_all.items():
            feat = strat_data.get("features", {})
            if "atr" in feat and feat["atr"] is not None and feat["atr"] > 0:
                atr = feat["atr"]
                break

        if atr is not None and price > 0:
            sl_pct = min(max((2.0 * atr) / price, 0.005), 0.05)  # Clamp: 0.5%-5%
            tp_pct = min(max((3.0 * atr) / price, 0.01), 0.10)   # Clamp: 1%-10%
        else:
            sl_pct = 0.02
            tp_pct = 0.04

        return sl_pct, tp_pct

    async def on_stop(self) -> None:
        self.logger.info("Strategy Generation Agent stopping")

    async def health(self) -> dict[str, Any]:
        base = await super().health()
        base.update({
            "strategies": list(self._strategies.keys()),
            "instruments_tracked": len(self._tick_prices) + len(self._candle_prices),
            "positions_tracked": len(position_registry.get_all_positions()),
            "cooldown_active": [
                k for k, v in self._last_signal_time.items()
                if time.monotonic() - v < _SIGNAL_COOLDOWN_SECONDS
            ],
        })
        return base


from src.strategies.base import Strategy


