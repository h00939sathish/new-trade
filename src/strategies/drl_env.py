import logging
from typing import Any

import numpy as np
import pandas as pd

try:
    import gymnasium as gym
    from gymnasium import spaces

    _BASE = gym.Env  # type: ignore
except ImportError:
    _BASE = object
    spaces = None  # type: ignore

logger = logging.getLogger(__name__)

EPS = 1e-8
N_FEATURES = 7  # ret, log_ret, vol_20, atr_ratio, rsi, bb_pos, norm_vol


def compute_features(df: pd.DataFrame) -> np.ndarray:
    """Compute 7-column feature matrix from OHLCV DataFrame."""
    closes = df["close"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    volumes = df["volume"].values.astype(np.float64)

    ret = np.diff(closes) / (closes[:-1] + EPS)
    ret = np.concatenate([[0.0], ret])

    log_ret = np.diff(np.log(closes + EPS))
    log_ret = np.concatenate([[0.0], log_ret])

    vol_20 = pd.Series(ret).rolling(20).std().fillna(0).values * np.sqrt(252)

    tr = np.maximum(
        highs - lows,
        np.maximum(
            np.abs(highs - np.concatenate([[closes[0]], closes[:-1]])),
            np.abs(lows - np.concatenate([[closes[0]], closes[:-1]])),
        ),
    )
    atr_14 = (pd.Series(tr).rolling(14).mean().fillna(pd.Series(tr))).values

    delta = np.diff(closes)
    delta = np.concatenate([[0.0], delta])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).rolling(14).mean().fillna(0).values
    avg_loss = pd.Series(loss).rolling(14).mean().fillna(0).values
    rs = avg_gain / (avg_loss + EPS)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    bb_window = 20
    bb_mid = (pd.Series(closes).rolling(bb_window).mean().fillna(pd.Series(closes))).values
    bb_std = pd.Series(closes).rolling(bb_window).std().fillna(0).values
    bb_position = (closes - bb_mid) / (bb_std * 2 + EPS)

    features = np.column_stack([
        ret, log_ret, vol_20,
        atr_14 / (closes + EPS),
        rsi / 100.0,
        bb_position,
        volumes / (volumes.mean() + EPS),
    ])
    features = np.nan_to_num(features, nan=0.0, posinf=1.0, neginf=-1.0)
    return features.astype(np.float32)


def build_observation(
    features: np.ndarray,
    current_step: int,
    lookback: int,
    portfolio_value: float = 0.0,
    position: int = 0,
    quantity: float = 0.0,
    cost_basis: float = 0.0,
    peak_value: float = 0.0,
    total_steps: int = 500,
) -> np.ndarray:
    """Build the complete observation vector."""
    start = max(0, current_step - lookback + 1)
    feat_slice = features[start : current_step + 1]
    if len(feat_slice) < lookback:
        pad = np.repeat(feat_slice[:1], lookback - len(feat_slice), axis=0)
        feat_slice = np.concatenate([pad, feat_slice], axis=0)

    flat = feat_slice.ravel()
    cost_val = cost_basis * quantity
    unrealized_pnl = (portfolio_value - abs(cost_val)) / (abs(cost_val) + EPS) if quantity != 0 else 0.0
    drawdown = (peak_value - portfolio_value) / (peak_value + EPS) if peak_value > 0 else 0.0
    step_sin = np.sin(2 * np.pi * current_step / max(total_steps, 1))
    step_cos = np.cos(2 * np.pi * current_step / max(total_steps, 1))

    state_vars = np.array([position, unrealized_pnl, drawdown, step_sin, step_cos], dtype=np.float32)
    return np.concatenate([flat, state_vars])


class StockTradingEnv(_BASE):
    """Gymnasium-compatible stock trading environment.

    Observation (n_features):
      - lookback window of returns, vol, ATR/price, RSI, BB position, norm volume
      - position state, unrealized PnL %, drawdown %, step sin/cos encoding

    Action: Discrete(3)  0=sell  1=hold  2=buy

    Reward: Δ(portfolio value) − transaction costs − volatility penalty

    Inherits from gym.Env when gymnasium is available (for SB3 compatibility),
    falls back to object when not (for strategy registry).
    """

    metadata = {"render_modes": ["log"]}  # type: ignore

    def __init__(
        self,
        df: pd.DataFrame,
        lookback: int = 60,
        initial_capital: float = 1_000_000.0,
        commission_pct: float = 0.0003,
        slippage_bps: float = 5.0,
        volatility_penalty_coeff: float = 0.5,
        reward_scaling: float = 1.0,
    ):
        self.df = df.reset_index(drop=True)
        self.lookback = lookback
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_bps = slippage_bps
        self.volatility_penalty_coeff = volatility_penalty_coeff
        self.reward_scaling = reward_scaling

        self._features: np.ndarray = self._compute_features()
        self.n_features = self._features.shape[1]
        self._obs_dim = self.n_features * self.lookback + 5

        if spaces is not None:
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(self._obs_dim,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(3)

        self._current_step: int = 0
        self._cash: float = initial_capital
        self._quantity: float = 0.0  # positive=long, negative=short
        self._cost_basis: float = 0.0  # avg entry price
        self._peak_value: float = initial_capital
        self._returns_history: list[float] = []

    # ── portfolio helpers ──────────────────────────────────────────

    def _portfolio_value(self, price: float | None = None) -> float:
        if price is None:
            price = self._current_price()
        return self._cash + self._quantity * price

    def _position(self) -> int:
        if self._quantity > 0:
            return 1
        if self._quantity < 0:
            return -1
        return 0

    # ── feature computation ────────────────────────────────────────

    def _compute_features(self) -> np.ndarray:
        return compute_features(self.df)

    def _get_obs(self) -> np.ndarray:
        return build_observation(
            features=self._features,
            current_step=self._current_step,
            lookback=self.lookback,
            portfolio_value=self._portfolio_value(),
            position=self._position(),
            quantity=self._quantity,
            cost_basis=self._cost_basis,
            peak_value=self._peak_value,
            total_steps=len(self.df),
        )

    def _current_price(self) -> float:
        return float(self.df.iloc[self._current_step]["close"])

    def _simulate_fill(self, is_buy: bool) -> float:
        price = self._current_price()
        slippage = price * (self.slippage_bps / 10000.0)
        return price + slippage if is_buy else price - slippage

    def _compute_transaction_cost(self, value: float) -> float:
        from src.risk.costs import TransactionCostModel

        cost_model = TransactionCostModel(
            brokerage_pct=self.commission_pct, slippage_bps=self.slippage_bps
        )
        return cost_model.total_cost("buy", 1, value, product="mis") * (value / (1 + 1e-8))

    # ── gym interface ──────────────────────────────────────────────

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        if seed is not None:
            np.random.seed(seed)
        self._current_step = self.lookback
        self._cash = self.initial_capital
        self._quantity = 0.0
        self._cost_basis = 0.0
        self._peak_value = self.initial_capital
        self._returns_history = []
        return self._get_obs(), {}

    def step(self, action: int):
        price = self._current_price()
        prev_value = self._portfolio_value(price)

        truncated = False

        if action == 2 and self._position() <= 0:  # buy / cover
            amount = prev_value * 0.98
            qty = int(amount / price)
            is_close_short = self._position() == -1
            self._execute_buy(qty, price, is_close_short)

        elif action == 0 and self._position() >= 0:  # sell / short
            amount = prev_value * 0.98
            qty = int(amount / price)
            is_close_long = self._position() == 1
            self._execute_sell(qty, price, is_close_long)

        self._current_step += 1
        current_value = self._portfolio_value()

        if current_value > self._peak_value:
            self._peak_value = current_value

        step_return = (current_value - prev_value) / (prev_value + 1e-8)
        self._returns_history.append(step_return)

        vol_penalty = 0.0
        if len(self._returns_history) > 20:
            recent_vol = float(np.std(self._returns_history[-20:]))
            vol_penalty = self.volatility_penalty_coeff * recent_vol * abs(step_return)

        # estimate transaction cost as fraction of portfolio
        trade_value = abs(current_value - prev_value)
        txn_frac = (
            self._compute_transaction_cost(trade_value) / (prev_value + 1e-8)
            if trade_value > 0
            else 0.0
        )

        reward = step_return * self.reward_scaling - vol_penalty - txn_frac

        terminated = self._current_step >= len(self.df) - 1
        if current_value <= 0:
            terminated = True
            reward -= 10.0

        return self._get_obs(), float(reward), terminated, truncated, {}

    def _execute_buy(self, qty: int, price: float, is_close_short: bool):
        if qty <= 0:
            return
        if is_close_short:
            cover = min(qty, abs(self._quantity))
            pnl = (self._cost_basis - price) * cover
            self._cash += pnl
            self._quantity += cover
            qty -= cover
        if qty > 0:
            cost = qty * price
            self._cash -= cost
            self._quantity += qty
            self._cost_basis = price

    def _execute_sell(self, qty: int, price: float, is_close_long: bool):
        if qty <= 0:
            return
        if is_close_long:
            sell = min(qty, self._quantity)
            pnl = (price - self._cost_basis) * sell
            self._cash += pnl
            self._quantity -= sell
            qty -= sell
        if qty > 0:
            self._cash += qty * price
            self._quantity -= qty
            self._cost_basis = price

    def render(self):
        pv = self._portfolio_value()
        logger.info(
            "Step=%d | Pos=%d | Qty=%.0f | Cash=%.0f | Value=%.0f | Peak=%.0f | DD=%.2f%%",
            self._current_step,
            self._position(),
            self._quantity,
            self._cash,
            pv,
            self._peak_value,
            (self._peak_value - pv) / self._peak_value * 100 if self._peak_value > 0 else 0,
        )
