from datetime import UTC, datetime

import pytest

from src.backtest.walk_forward import WalkForwardValidator


@pytest.mark.asyncio
async def test_walk_forward_validator():
    ticks = []
    # Day 1: Price goes up
    ticks.extend([
        {"instrument": "TEST", "price": 100.0 + i * 0.5, "volume": 1000, "timestamp": datetime(2026, 5, 25, 9, 15 + i, 0, tzinfo=UTC).isoformat()}
        for i in range(10)
    ])
    # Day 2: Price goes down
    ticks.extend([
        {"instrument": "TEST", "price": 105.0 - i * 0.5, "volume": 1000, "timestamp": datetime(2026, 5, 26, 9, 15 + i, 0, tzinfo=UTC).isoformat()}
        for i in range(10)
    ])
    # Day 3: Price rises again
    ticks.extend([
        {"instrument": "TEST", "price": 100.0 + i * 1.0, "volume": 1000, "timestamp": datetime(2026, 5, 27, 9, 15 + i, 0, tzinfo=UTC).isoformat()}
        for i in range(10)
    ])

    validator = WalkForwardValidator(
        train_days=2,
        test_days=1,
        parameter_grids={
            "momentum": {
                "short_window": [3],
                "long_window": [5],
                "threshold": [0.01],
            }
        }
    )

    result = await validator.run_validation("momentum", ticks, metric="total_pnl")

    assert result["strategy"] == "momentum"
    assert len(result["windows"]) == 1
    assert "overall_oos_performance" in result
    assert result["overall_oos_performance"]["total_trades"] >= 0
    assert isinstance(result["overall_oos_performance"]["final_value"], float)
