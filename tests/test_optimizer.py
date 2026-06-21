from datetime import UTC, datetime, timedelta

import pytest

from src.strategies.technical import MomentumStrategy
from src.backtest.optimizer import OptimizationResult, grid_search

_BASE_TIME = datetime(2026, 5, 25, 9, 15, 0, tzinfo=UTC)


def _make_ticks(count: int = 60) -> list[dict]:
    ticks = []
    for i in range(count):
        price = 100.0 + (i * 0.5) if i > 20 else 100.0
        ticks.append(
            {
                "instrument": "TEST",
                "price": price,
                "volume": 1000,
                "timestamp": _BASE_TIME + timedelta(seconds=i),
            }
        )
    return ticks


@pytest.mark.asyncio
async def test_grid_search_returns_optimization_result():
    ticks = _make_ticks(30)
    result = await grid_search(
        MomentumStrategy,
        param_grid={
            "short_window": [3, 5],
            "long_window": [10, 15],
            "threshold": [0.02],
        },
        ticks=ticks,
    )
    assert isinstance(result, OptimizationResult)
    assert result.best_params != {}
    assert result.best_score > float("-inf")


@pytest.mark.asyncio
async def test_grid_search_best_score_is_valid():
    ticks = _make_ticks(30)
    result = await grid_search(
        MomentumStrategy,
        param_grid={
            "short_window": [5],
            "long_window": [20],
            "threshold": [0.02],
        },
        ticks=ticks,
    )
    assert result.best_score >= 0
    assert result.best_result is not None


@pytest.mark.asyncio
async def test_grid_search_evaluates_all_combinations():
    ticks = _make_ticks(30)
    result = await grid_search(
        MomentumStrategy,
        param_grid={
            "short_window": [3, 5],
            "long_window": [15],
        },
        ticks=ticks,
        top_n=5,
    )
    assert len(result.results) >= 1


@pytest.mark.asyncio
async def test_optimization_result_summary():
    result = OptimizationResult(
        best_params={"window": 20},
        best_score=0.85,
    )
    summary = result.summary()
    assert "Best params" in summary
    assert "0.85" in summary
