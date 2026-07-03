import pytest


class TestOandaProfiles:
    def test_xau_usd_profile_exists(self):
        from src.config.oanda_profiles import OANDA_INSTRUMENT_PROFILES
        assert "XAU_USD" in OANDA_INSTRUMENT_PROFILES

    def test_profile_disables_vwap(self):
        from src.config.oanda_profiles import OANDA_INSTRUMENT_PROFILES
        profile = OANDA_INSTRUMENT_PROFILES["XAU_USD"]
        strategies = profile.get("strategies", {})
        assert strategies.get("vwap_reversion", {}).get("enabled") is False

    def test_eurusd_enables_sideways_reversion(self):
        from src.config.oanda_profiles import OANDA_INSTRUMENT_PROFILES
        profile = OANDA_INSTRUMENT_PROFILES["EUR_USD"]
        strategies = profile.get("strategies", {})
        assert strategies.get("sideways_reversion", {}).get("enabled") is True

    def test_eurusd_profile_exists(self):
        from src.config.oanda_profiles import OANDA_INSTRUMENT_PROFILES
        assert "EUR_USD" in OANDA_INSTRUMENT_PROFILES

    def test_load_oanda_profile_merges_with_default(self):
        from src.config.oanda_profiles import load_oanda_profile
        config = load_oanda_profile("XAU_USD")
        assert config["strategies"]["momentum"]["weight"] == 0.6
        assert config["strategies"]["vol_breakout"]["enabled"] is True

    def test_load_oanda_profile_unknown_instrument_returns_default(self):
        from src.config.oanda_profiles import load_oanda_profile
        config = load_oanda_profile("UNKNOWN")
        assert config["strategies"]["momentum"]["weight"] == 0.4
