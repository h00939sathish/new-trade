#!/usr/bin/env python3
"""
Train a DRL agent (PPO) on historical market data.

Usage:
    uv run python scripts/train_drl.py                          # defaults
    uv run python scripts/train_drl.py --symbols RELIANCE,TCS    # custom symbols
    uv run python scripts/train_drl.py --timesteps 200_000       # more training
"""

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("train_drl")


def download_data(
    symbols: list[str],
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """Download OHLCV data for each symbol using yfinance."""
    import yfinance as yf

    data: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        yahoo_sym = f"{sym}.NS"
        logger.info("Downloading %s [%s .. %s] @ %s ...", yahoo_sym, start_date, end_date, interval)
        try:
            df = yf.download(
                yahoo_sym,
                start=start_date,
                end=end_date,
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
        except Exception as e:
            logger.warning("Failed to download %s: %s", yahoo_sym, e)
            continue
        if df is None or df.empty:
            logger.warning("No data for %s", yahoo_sym)
            continue

        df = df.reset_index()
        # Flatten MultiIndex columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        if "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})
        if "adj close" in df.columns:
            df = df.drop(columns=["adj close"])
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        data[sym] = df
        logger.info("  -> %d rows", len(df))
    return data


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add common technical indicators used by the trading system."""
    df = df.copy()

    # SMA / EMA
    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df["ema_12"] = df["close"].ewm(span=12).mean()
    df["ema_26"] = df["close"].ewm(span=26).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-8)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # MACD
    df["macd"] = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = df["macd"].ewm(span=9).mean()

    # Bollinger Bands
    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (bb_mid + 1e-8)

    # ATR
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    # Volume indicators
    df["volume_sma"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / (df["volume_sma"] + 1e-8)

    df = df.ffill().bfill().fillna(0)
    return df


def train(
    df: pd.DataFrame,
    total_timesteps: int = 100_000,
    model_dir: str = "models",
    model_name: str = "drl_agent",
    tb_log_dir: str = "logs/tb",
):
    """Train PPO agent on the given DataFrame."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from src.strategies.drl_env import StockTradingEnv

    model_dir_path = Path(model_dir)
    model_dir_path.mkdir(parents=True, exist_ok=True)

    Path(tb_log_dir).mkdir(parents=True, exist_ok=True)

    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].reset_index(drop=True)
    eval_df = df.iloc[split_idx:].reset_index(drop=True)

    logger.info("Train samples: %d | Eval samples: %d", len(train_df), len(eval_df))

    def make_train_env():
        return StockTradingEnv(train_df, lookback=60)

    def make_eval_env():
        return StockTradingEnv(eval_df, lookback=60)

    train_env = DummyVecEnv([make_train_env])
    eval_env = DummyVecEnv([make_eval_env])

    train_env = VecNormalize(train_env, norm_obs=True, norm_reward=True, clip_obs=10.0)
    eval_env = VecNormalize(
        eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0, training=False
    )

    checkpoint_callback = CheckpointCallback(
        save_freq=max(total_timesteps // 10, 1_000),
        save_path=str(model_dir_path),
        name_prefix=model_name,
    )
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=str(model_dir_path / "best"),
        log_path=tb_log_dir,
        eval_freq=max(total_timesteps // 20, 1_000),
        deterministic=True,
        render=False,
    )

    model = PPO(
        "MlpPolicy",
        train_env,
        verbose=1,
        tensorboard_log=tb_log_dir,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
    )

    logger.info("Starting training for %d timesteps ...", total_timesteps)
    start = time.time()
    model.learn(
        total_timesteps=total_timesteps,
        callback=[checkpoint_callback, eval_callback],
        tb_log_name=model_name,
    )
    elapsed = time.time() - start
    logger.info("Training complete in %.1fs", elapsed)

    model_path = str(model_dir_path / f"{model_name}.zip")
    model.save(model_path)
    logger.info("Model saved to %s", model_path)

    norm_path = str(model_dir_path / f"{model_name}_vecnormalize.pkl")
    train_env.save(norm_path)
    logger.info("VecNormalize saved to %s", norm_path)

    return model_path, norm_path


def main():
    parser = argparse.ArgumentParser(description="Train DRL trading agent")
    parser.add_argument(
        "--symbols",
        default="RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK",
        help="Comma-separated symbols to train on",
    )
    parser.add_argument("--start", default="2020-01-01", help="Start date")
    parser.add_argument("--end", default=None, help="End date (default: today)")
    parser.add_argument("--interval", default="1d", help="Data interval (1d, 1h, etc.)")
    parser.add_argument("--timesteps", type=int, default=100_000, help="Total training timesteps")
    parser.add_argument("--model-dir", default="models", help="Model output directory")
    parser.add_argument("--model-name", default="drl_agent", help="Model name")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    end_date = args.end or datetime.now(UTC).strftime("%Y-%m-%d")

    logger.info("Downloading data for %s ...", symbols)
    raw_data = download_data(symbols, args.start, end_date, args.interval)
    if not raw_data:
        logger.error("No data downloaded — aborting")
        sys.exit(1)

    # Combine all symbols into a single training set (interleaving by date)
    combined = pd.concat(
        [add_technical_indicators(df).assign(symbol=sym) for sym, df in raw_data.items()],
        ignore_index=True,
    )
    combined = combined.sort_values(["timestamp"]).reset_index(drop=True)
    logger.info("Combined dataset: %d rows across %d symbols", len(combined), len(raw_data))

    # For multi-symbol training, we use the mean of close prices
    # as a simple market index for the env
    pivoted = combined.pivot_table(index="timestamp", columns="symbol", values="close")
    pivoted["close"] = pivoted.mean(axis=1)
    pivoted["high"] = combined.pivot_table(
        index="timestamp", columns="symbol", values="high"
    ).mean(axis=1)
    pivoted["low"] = combined.pivot_table(
        index="timestamp", columns="symbol", values="low"
    ).mean(axis=1)
    pivoted["volume"] = combined.pivot_table(
        index="timestamp", columns="symbol", values="volume"
    ).sum(axis=1)
    pivoted = pivoted.reset_index().ffill().bfill().dropna()

    logger.info("Training on market-aggregated data (%d rows)", len(pivoted))

    model_path, norm_path = train(
        pivoted,
        total_timesteps=args.timesteps,
        model_dir=args.model_dir,
        model_name=args.model_name,
    )

    print(f"\n{'='*60}")
    print("Training complete!")
    print(f"  Model:        {model_path}")
    print(f"  VecNormalize: {norm_path}")
    print("  To use in the live system:")
    print("    Enable in config/strategy_config.yaml:")
    print('      drl_ensemble:')
    print("        enabled: true")
    print("        weight: 0.3")
    print("        params:")
    print(f"          model_path: {model_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
