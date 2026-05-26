import pytest

from src.strategies.stat_arb import StatArbStrategy


@pytest.mark.asyncio
async def test_stat_arb_insufficient_data():
    strategy = StatArbStrategy(window=10)
    prices = [100.0] * 5
    result1 = await strategy.evaluate("TCS", prices)
    result2 = await strategy.evaluate("INFY", prices)
    assert result1 is None
    assert result2 is None

@pytest.mark.asyncio
async def test_stat_arb_signal():
    strategy = StatArbStrategy(window=10, entry_z=1.0)

    # Base prices
    tcs_prices = [100.0] * 10
    infy_prices = [100.0] * 10

    # Load history
    await strategy.evaluate("TCS", tcs_prices)
    await strategy.evaluate("INFY", infy_prices)

    # Sudden divergence: TCS jumps
    tcs_prices.append(110.0)
    infy_prices.append(100.0)

    # We must evaluate TCS to have same length of prices inside the strategy
    res_tcs = await strategy.evaluate("TCS", tcs_prices)

    # Now evaluate INFY again so it sees the updated spread
    res_infy2 = await strategy.evaluate("INFY", infy_prices)

    # Since TCS jumped, spread (TCS-INFY) is positive, z_score > 1.0
    # Thus Primary (TCS) is overvalued -> SHORT TCS, LONG INFY
    assert res_tcs is not None
    assert res_tcs["direction"] == "short"

    assert res_infy2 is not None
    assert res_infy2["direction"] == "long"
