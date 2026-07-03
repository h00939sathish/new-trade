#!/usr/bin/env python3
"""
Backtest a trained DRL agent against historical data.

Usage:
    uv run python scripts/backtest_drl.py --model models/drl_agent.zip
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backtest_drl")


def backtest(
    model_path: str,
    df: pd.DataFrame,
    norm_path: str | None = None,
    lookback: int = 60,
    initial_capital: float = 1_000_000.0,
) -> dict:
    """Run a deterministic backtest of the trained model on df."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from src.strategies.drl_env import StockTradingEnv

    env = StockTradingEnv(
        df, lookback=lookback, initial_capital=initial_capital
    )
    vec_env = DummyVecEnv([lambda: env])

    if norm_path and Path(norm_path).exists():
        vec_env = VecNormalize.load(norm_path, vec_env)
        vec_env.training = False
        vec_env.norm_reward = False

    model = PPO.load(model_path)

    obs = vec_env.reset()
    done = False

    equity_curve: list[float] = [initial_capital]
    trades: list[dict] = []
    position_log: list[int] = []
    actions_log: list[int] = []

    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, info = vec_env.step(action)
        actions_log.append(int(action[0]))
        position_log.append(env._position())

        value = env._portfolio_value()
        equity_curve.append(value)

        prev_value = equity_curve[-2] if len(equity_curve) > 1 else initial_capital
        if abs(value - prev_value) / (prev_value + 1e-8) > 0.001:
            trades.append({
                "step": env._current_step,
                "action": int(action[0]),
                "position": env._position,
                "price": env._current_price(),
                "value": value,
            })

    equity = np.array(equity_curve)
    returns = np.diff(equity) / (equity[:-1] + 1e-8)

    peak = np.maximum.accumulate(equity)
    drawdowns = (peak - equity) / peak
    max_dd = float(np.max(drawdowns))
    final_value = float(equity[-1])
    total_return = (final_value - initial_capital) / initial_capital * 100

    sharpe = 0.0
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252))

    sortino = 0.0
    neg_ret = returns[returns < 0]
    if len(neg_ret) > 0 and np.std(neg_ret) > 0:
        sortino = float(np.mean(returns) / np.std(neg_ret) * np.sqrt(252))

    wins = returns[returns > 0]
    losses = returns[returns < 0]
    win_rate = float(len(wins) / len(returns)) if len(returns) > 0 else 0.0
    profit_factor = float(sum(wins) / abs(sum(losses))) if len(losses) > 0 and abs(sum(losses)) > 0 else float("inf")

    action_counts = pd.Series(actions_log).value_counts().to_dict()
    position_pct = pd.Series(position_log).value_counts(normalize=True).to_dict()

    return {
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": round(total_return, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate": round(win_rate * 100, 1),
        "profit_factor": round(profit_factor, 2),
        "total_steps": int(len(equity_curve) - 1),
        "total_trades": len(trades),
        "action_distribution": {str(k): int(v) for k, v in action_counts.items()},
        "position_time_pct": {str(k): round(v * 100, 1) for k, v in position_pct.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest DRL agent")
    parser.add_argument("--model", default="models/drl_agent.zip", help="Path to trained model")
    parser.add_argument("--norm", default=None, help="Path to VecNormalize pickle")
    parser.add_argument("--symbol", default="RELIANCE", help="Symbol to backtest on")
    parser.add_argument("--start", default="2023-01-01", help="Backtest start")
    parser.add_argument("--end", default=None, help="Backtest end")
    parser.add_argument("--interval", default="1d", help="Data interval")
    args = parser.parse_args()

    import yfinance as yf

    end_date = args.end or datetime.now(UTC).strftime("%Y-%m-%d")
    yahoo_sym = f"{args.symbol}.NS"
    logger.info("Downloading %s [%s .. %s]", yahoo_sym, args.start, end_date)
    df = yf.download(
        yahoo_sym,
        start=args.start,
        end=end_date,
        interval=args.interval,
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        logger.error("No data for %s", yahoo_sym)
        sys.exit(1)

    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns:
        df = df.rename(columns={"date": "timestamp"})
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])

    logger.info("Running backtest with %d rows ...", len(df))
    results = backtest(args.model, df, norm_path=args.norm)

    print(f"\n{'='*50}")
    print(f"  DRL Backtest Results — {args.symbol}")
    print(f"{'='*50}")
    print(f"  Period:          {args.start} -> {end_date}")
    print(f"  Initial Capital: ₹{results['initial_capital']:,.0f}")
    print(f"  Final Value:     ₹{results['final_value']:,.0f}")
    print(f"  Total Return:    {results['total_return_pct']:+.2f}%")
    print(f"  Sharpe Ratio:    {results['sharpe_ratio']}")
    print(f"  Sortino Ratio:   {results['sortino_ratio']}")
    print(f"  Max Drawdown:    {results['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate:        {results['win_rate']:.1f}%")
    print(f"  Profit Factor:   {results['profit_factor']}")
    print(f"  Total Steps:     {results['total_steps']}")
    print(f"  Total Trades:    {results['total_trades']}")
    print(f"  Position Split:  {results['position_time_pct']}")
    print(f"  Action Dist:     {results['action_distribution']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
