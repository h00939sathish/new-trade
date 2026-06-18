import asyncio
import itertools
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from src.backtest.engine import BacktestEngine
from src.connectors.backtest_provider import generate_synthetic_ticks
from src.strategies import STRATEGY_REGISTRY

ARTIFACTS_DIR = Path(
    r"C:\Users\h0093\.gemini\antigravity\brain\75be7a45-b180-4d14-a8cd-6190d9fbce7a"
)


async def generate_heatmaps():
    print("Generating synthetic data for optimization...")
    ticks = generate_synthetic_ticks(n=5000)

    # Grid search for ml_regime
    ml_grid = {"lookback_window": [50, 100, 150], "prediction_horizon": [3, 5, 10]}

    # Grid search for vol_breakout
    vol_grid = {"window": [10, 20, 30, 40, 50]}

    strategies_to_test = [
        ("ml_regime", ml_grid, "sharpe_ratio"),
        ("vol_breakout", vol_grid, "total_pnl"),
    ]

    for strategy_name, grid, metric in strategies_to_test:
        print(f"Optimizing {strategy_name}...")

        keys = list(grid.keys())
        values = list(grid.values())
        combinations = [dict(zip(keys, prod)) for prod in itertools.product(*values)]

        results = []
        strat_cls = STRATEGY_REGISTRY[strategy_name]

        for combo in combinations:
            engine = BacktestEngine(initial_capital=1000000.0)
            engine._strategy_gen.register_strategy(strat_cls(**combo))
            res = await engine.run(ticks)

            row = combo.copy()
            row["sharpe_ratio"] = getattr(res, "sharpe_ratio", 0.0)
            row["total_pnl"] = getattr(res, "total_pnl", 0.0)
            row["win_rate"] = getattr(res, "win_rate", 0.0)
            results.append(row)

        df = pd.DataFrame(results)

        if len(keys) >= 2:
            # 2D Heatmap
            pivot_metric = df.pivot(index=keys[0], columns=keys[1], values=metric)
            plt.figure(figsize=(10, 8))
            sns.heatmap(pivot_metric, annot=True, cmap="viridis", fmt=".2f")
            plt.title(f"{strategy_name.upper()} - {metric.replace('_', ' ').title()}")
            plt.tight_layout()
            out_path = ARTIFACTS_DIR / f"{strategy_name}_{metric}_heatmap.png"
            plt.savefig(out_path)
            print(f"Saved {out_path}")
            plt.close()
        else:
            # 1D Line plot
            plt.figure(figsize=(10, 6))
            sns.lineplot(data=df, x=keys[0], y=metric, marker="o")
            plt.title(f"{strategy_name.upper()} - {metric.replace('_', ' ').title()}")
            plt.grid(True)
            plt.tight_layout()
            out_path = ARTIFACTS_DIR / f"{strategy_name}_{metric}_plot.png"
            plt.savefig(out_path)
            print(f"Saved {out_path}")
            plt.close()


if __name__ == "__main__":
    asyncio.run(generate_heatmaps())
