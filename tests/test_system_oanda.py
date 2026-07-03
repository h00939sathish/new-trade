import sys
from unittest.mock import patch

import pytest


def _unload_system_module():
    if "src.system" in sys.modules:
        del sys.modules["src.system"]


class TestSystemOandaWiring:
    def teardown_method(self):
        _unload_system_module()

    def test_system_detects_oanda_settings(self):
        _unload_system_module()
        with patch("src.config.settings.settings") as mock_settings:
            mock_settings.oanda_api_key = "test_key"
            mock_settings.oanda_account_id = "test_id"
            mock_settings.oanda_environment = "practice"
            mock_settings.oanda_enabled_instruments = "XAU_USD,EUR_USD"
            mock_settings.oanda_execution_mode = "internal_simulation"
            mock_settings.angel_api_key = ""
            mock_settings.groww_api_key = ""
            mock_settings.live_trading_enabled = False
            from src.system import TradingSystem

            system = TradingSystem()
            assert system._oanda_provider is not None
            assert system._oanda_broker is None

    def test_oanda_broker_created_in_practice_mode(self):
        _unload_system_module()
        with patch("src.config.settings.settings") as mock_settings:
            mock_settings.oanda_api_key = "test_key"
            mock_settings.oanda_account_id = "test_id"
            mock_settings.oanda_environment = "practice"
            mock_settings.oanda_enabled_instruments = "XAU_USD,EUR_USD"
            mock_settings.oanda_execution_mode = "oanda_practice"
            mock_settings.angel_api_key = ""
            mock_settings.groww_api_key = ""
            mock_settings.live_trading_enabled = False
            from src.system import TradingSystem

            system = TradingSystem()
            assert system._oanda_broker is not None
