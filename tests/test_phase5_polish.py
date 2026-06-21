import pytest

from src.risk.market_impact import MarketImpactModel
from src.risk.nse_lot_sizes import NSE_LOT_SIZES, validate_lot_size
from src.risk.position_registry import PositionRegistry


class TestNseLotSizes:
    def test_known_symbol_rejects_invalid_qty(self):
        passed, msg = validate_lot_size("RELIANCE", 100)
        assert not passed
        assert "lot size" in msg

    def test_known_symbol_accepts_multiple(self):
        passed, msg = validate_lot_size("RELIANCE", 250)
        assert passed
        assert "1 lot(s) of 250" in msg

    def test_known_symbol_accepts_multiple_lots(self):
        passed, msg = validate_lot_size("RELIANCE", 500)
        assert passed
        assert "2 lot(s) of 250" in msg

    def test_unknown_symbol_passes(self):
        passed, msg = validate_lot_size("UNKNOWN", 100)
        assert passed
        assert msg == ""

    def test_case_insensitive(self):
        passed, msg = validate_lot_size("reliance", 250)
        assert passed

    def test_lot_sizes_are_positive(self):
        for symbol, size in NSE_LOT_SIZES.items():
            assert size > 0, f"{symbol} has non-positive lot size {size}"


class TestMarketImpactModel:
    def test_zero_impact_for_zero_qty(self):
        model = MarketImpactModel()
        impact = model.estimate_impact_bps(0, 1_000_000, 0.02)
        assert impact == 0.0

    def test_zero_impact_for_zero_adv(self):
        model = MarketImpactModel()
        impact = model.estimate_impact_bps(1000, 0, 0.02)
        assert impact == 0.0

    def test_small_order_low_impact(self):
        model = MarketImpactModel()
        impact = model.estimate_impact_bps(100, 1_000_000, 0.02)
        assert 0 < impact < 10.0

    def test_large_order_high_impact(self):
        model = MarketImpactModel()
        impact = model.estimate_impact_bps(100_000, 500_000, 0.03)
        assert impact > 20.0

    def test_significant_flag(self):
        model = MarketImpactModel()
        sig, impact = model.is_significant(100_000, 500_000, 0.03)
        assert sig
        assert impact > 20.0

    def test_not_significant_for_small_order(self):
        model = MarketImpactModel()
        sig, impact = model.is_significant(100, 1_000_000, 0.02)
        assert not sig


@pytest.mark.asyncio
class TestPositionRegistryTaxLots:
    async def test_average_cost_default(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        await reg.update_from_fill("TEST", "buy", 100, 10.0)
        await reg.update_from_fill("TEST", "sell", 50, 12.0)
        pos = reg.get_position("TEST")
        assert pos["quantity"] == 50
        assert pos["avg_price"] == 10.0
        assert pos["realized_pnl"] == pytest.approx(100.0)

    async def test_fifo_cost_basis(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        reg._tax_lot_method = "fifo"
        await reg.update_from_fill("TEST", "buy", 100, 10.0)
        await reg.update_from_fill("TEST", "buy", 100, 20.0)
        await reg.update_from_fill("TEST", "sell", 100, 15.0)
        pos = reg.get_position("TEST")
        assert pos["quantity"] == 100
        assert pos["realized_pnl"] == pytest.approx(500.0)
        assert pos["avg_price"] == 20.0

    async def test_fifo_consumes_oldest_lot_first(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        reg._tax_lot_method = "fifo"
        await reg.update_from_fill("TEST", "buy", 50, 10.0)
        await reg.update_from_fill("TEST", "buy", 50, 20.0)
        await reg.update_from_fill("TEST", "buy", 50, 30.0)
        await reg.update_from_fill("TEST", "sell", 100, 25.0)
        pos = reg.get_position("TEST")
        assert pos["quantity"] == 50
        assert pos["realized_pnl"] == pytest.approx(
            50 * (25 - 10) + 50 * (25 - 20)
        )

    async def test_specific_id_requires_lot_id(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        reg._tax_lot_method = "specific_id"
        with pytest.raises(ValueError, match="specific_id.*requires lot_id"):
            await reg.update_from_fill("TEST", "sell", 100, 15.0)

    async def test_specific_id_unknown_lot_raises(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        reg._tax_lot_method = "specific_id"
        await reg.update_from_fill("TEST", "buy", 100, 10.0, lot_id="LOT1")
        with pytest.raises(ValueError, match="Lot UNKNOWN not found"):
            await reg.update_from_fill("TEST", "sell", 50, 15.0, lot_id="UNKNOWN")

    async def test_specific_id_closes_correct_lot(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        reg._tax_lot_method = "specific_id"
        await reg.update_from_fill("TEST", "buy", 100, 10.0, lot_id="LOT1")
        await reg.update_from_fill("TEST", "buy", 100, 20.0, lot_id="LOT2")
        await reg.update_from_fill("TEST", "sell", 50, 15.0, lot_id="LOT1")
        pos = reg.get_position("TEST")
        assert pos["quantity"] == 150
        assert pos["realized_pnl"] == pytest.approx(50 * (15 - 10))

    async def test_reset_clears_lots_and_pnl(self):
        PositionRegistry.reset_singleton()
        reg = PositionRegistry()
        await reg.update_from_fill("TEST", "buy", 100, 10.0)
        reg.reset()
        pos = reg.get_position("TEST")
        assert pos["quantity"] == 0
        assert pos["realized_pnl"] == 0.0
        assert len(pos["lots"]) == 0
