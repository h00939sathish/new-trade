import asyncio
from src.strategies.volatility_compression import VolatilityCompressionStrategy

async def run(): 
    strategy = VolatilityCompressionStrategy(bb_window=5, lookback=10, atr_window=3)
    prices = [100.0, 110.0, 90.0, 105.0, 95.0, 108.0, 92.0, 100.0] * 3
    highs = [p + 5 for p in prices]
    lows = [p - 5 for p in prices]
    for _ in range(10):
        prices.append(100.0)
        highs.append(100.5)
        lows.append(99.5)
    prices.append(105.0)
    highs.append(106.0)
    lows.append(100.0)
    
    # We debug internals manually:
    bb_widths = []
    for i in range(len(prices) - strategy.lookback, len(prices) + 1):
        window_prices = prices[i - strategy.bb_window : i]
        import numpy as np
        mean = np.mean(window_prices)
        std = np.std(window_prices)
        if mean > 0:
            upper = mean + strategy.bb_std * std
            lower = mean - strategy.bb_std * std
            width = (upper - lower) / mean
            bb_widths.append(width)
        else:
            bb_widths.append(0.0)
    print("bb_widths:", bb_widths)
    print("current_width:", bb_widths[-2])
    history_widths = bb_widths[:-2]
    percentile = sum(1 for w in history_widths if w < bb_widths[-2]) / len(history_widths) * 100.0
    print("percentile:", percentile)

    trs = []
    for j in range(len(prices) - strategy.atr_window * 2, len(prices)):
        tr = max(
            highs[j] - lows[j],
            abs(highs[j] - prices[j-1]),
            abs(lows[j] - prices[j-1])
        )
        trs.append(tr)
    print("trs:", trs)
    
    atr_history = []
    for i in range(strategy.atr_window, len(trs) + 1):
        atr_history.append(np.mean(trs[i - strategy.atr_window : i]))
    print("atr_history:", atr_history)
    print("prev_atr:", atr_history[-2])
    print("atr_ma:", np.mean(atr_history[:-2]))

    sig = await strategy.evaluate('RELIANCE', prices=prices, highs=highs, lows=lows)
    print("sig:", sig)

asyncio.run(run())
