from typing import Any


class Strategy:
    name: str
    data_type: str = "any"  # "tick", "candle", or "any"
    timeframe: str = "minute"

    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None: ...
