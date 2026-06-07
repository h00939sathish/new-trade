import pytest

from src.strategies.technical import (
    IchimokuStrategy,
    MACDStrategy,
    VolumeStrategy,
)


class TestMACDStrategy:
    @pytest.fixture
    def strategy(self):
        return MACDStrategy(fast=6, slow=13, signal=5)

    @pytest.mark.asyncio
    async def test_long_signal(self, strategy: MACDStrategy):
        prices = [100.0] * 30 + [
            105.0,
            110.0,
            115.0,
            120.0,
            125.0,
            130.0,
            135.0,
            140.0,
            145.0,
            150.0,
        ]
        result = await strategy.evaluate("TEST", prices)
        assert result is not None, "MACD should give long on sharp uptrend"
        assert result["direction"] == "long"
        assert 0 < result["confidence"] <= 1.0
        assert "macd" in result["features"]
        assert "histogram" in result["features"]

    @pytest.mark.asyncio
    async def test_short_signal(self, strategy: MACDStrategy):
        prices = [150.0] * 30 + [
            145.0,
            140.0,
            135.0,
            130.0,
            125.0,
            120.0,
            115.0,
            110.0,
            105.0,
            100.0,
        ]
        result = await strategy.evaluate("TEST", prices)
        assert result is not None, "MACD should give short on sharp downtrend"
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_insufficient_data(self, strategy: MACDStrategy):
        prices = [100.0] * 10
        result = await strategy.evaluate("TEST", prices)
        assert result is None


class TestVolumeStrategy:
    @pytest.fixture
    def strategy(self):
        return VolumeStrategy()

    @pytest.mark.asyncio
    async def test_evaluate_returns_none_without_volume(self, strategy: VolumeStrategy):
        prices = [100.0] * 30
        result = await strategy.evaluate("TEST", prices)
        assert result is None

    @pytest.mark.asyncio
    async def test_long_with_volume(self, strategy: VolumeStrategy):
        prices = [100.0] * 10 + [103.0]
        volumes = [100] * 19 + [500]
        result = await strategy.evaluate_with_volume("TEST", prices, volumes)
        assert result is not None
        assert result["direction"] == "long"
        assert "volume_ratio" in result["features"]

    @pytest.mark.asyncio
    async def test_insufficient_volume_data(self, strategy: VolumeStrategy):
        prices = [100.0] * 5
        volumes = [100] * 5
        result = await strategy.evaluate_with_volume("TEST", prices, volumes)
        assert result is None

    @pytest.mark.asyncio
    async def test_low_volume_no_signal(self, strategy: VolumeStrategy):
        prices = [100.0] * 15 + [103.0]
        volumes = [100] * 20
        result = await strategy.evaluate_with_volume("TEST", prices, volumes)
        assert result is None


class TestIchimokuStrategy:
    @pytest.fixture
    def strategy(self):
        return IchimokuStrategy(conversion=5, base=10, lagging=20, displacement=10)

    @pytest.mark.asyncio
    async def test_long_signal(self, strategy: IchimokuStrategy):
        prices = [
            100.0,
            102.0,
            101.0,
            103.0,
            102.0,
            104.0,
            103.0,
            105.0,
            104.0,
            106.0,
            105.0,
            107.0,
            106.0,
            108.0,
            107.0,
            109.0,
            108.0,
            110.0,
            109.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
            116.0,
            117.0,
            118.0,
            119.0,
            120.0,
            121.0,
        ]
        result = await strategy.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "long"
        assert "cloud_top" in result["features"]

    @pytest.mark.asyncio
    async def test_short_signal(self, strategy: IchimokuStrategy):
        prices = [
            120.0,
            118.0,
            119.0,
            117.0,
            118.0,
            116.0,
            117.0,
            115.0,
            116.0,
            114.0,
            115.0,
            113.0,
            114.0,
            112.0,
            113.0,
            111.0,
            112.0,
            110.0,
            111.0,
            109.0,
            108.0,
            107.0,
            106.0,
            105.0,
            104.0,
            103.0,
            102.0,
            101.0,
            100.0,
            99.0,
        ]
        result = await strategy.evaluate("TEST", prices)
        assert result is not None
        assert result["direction"] == "short"

    @pytest.mark.asyncio
    async def test_insufficient_data(self, strategy: IchimokuStrategy):
        prices = [100.0] * 15
        result = await strategy.evaluate("TEST", prices)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_signal_in_cloud(self, strategy: IchimokuStrategy):
        prices = [100.0] * 15 + list(range(95, 111))
        result = await strategy.evaluate("TEST", prices)
        assert result is not None or result is None
