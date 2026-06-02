import asyncio
import logging
import signal
from typing import Any

from src.agents import (
    AlertAgent,
    ExecutionAgent,
    ExpertPersonasAgent,
    MarketIntelAgent,
    PortfolioOptimizationAgent,
    ReflectionEngineAgent,
    RegimeDetectionAgent,
    RiskManagementAgent,
    StrategyGenAgent,
)
from src.agents.reconciliation import ReconciliationAgent
from src.config.settings import settings
from src.event_store import create_event_store


class TradingSystem:
    def __init__(self, event_store=None, providers: dict | None = None):
        self._event_store = event_store or create_event_store()
        self._groww_provider: Any | None = None
        self._angel_provider: Any | None = None
        self._kite_client: Any | None = None
        self._kite_broker: Any | None = None

        if providers is not None:
            self._angel_provider = providers.get("angel")
            self._groww_provider = providers.get("groww")
            self._kite_client = providers.get("kite_client")
            self._kite_broker = providers.get("kite_broker")
        else:
            if settings.angel_api_key:
                from src.connectors.angel import AngelMarketDataProvider
                self._angel_provider = AngelMarketDataProvider()

            if settings.groww_api_key:
                from src.connectors.groww import GrowwMarketDataProvider
                self._groww_provider = GrowwMarketDataProvider()

            if settings.kite_api_key and settings.kite_access_token:
                from src.connectors.kite import KiteBroker, KiteClient
                self._kite_client = KiteClient()
                self._kite_broker = KiteBroker(self._kite_client)

        if not self._angel_provider and not self._groww_provider:
            from src.connectors.jugaad import JugaadMarketDataProvider
            self._jugaad_provider = JugaadMarketDataProvider()
        else:
            self._jugaad_provider = None

        market_data_provider = self._angel_provider or self._groww_provider or self._jugaad_provider

        self.market_intel = MarketIntelAgent(
            event_store=self._event_store,
            market_data_provider=market_data_provider,
        )
        self.strategy_gen = StrategyGenAgent(event_store=self._event_store)
        self.risk_mgmt = RiskManagementAgent(event_store=self._event_store)
        self.execution = ExecutionAgent(
            event_store=self._event_store,
            broker=self._kite_broker,
        )
        self.portfolio_opt = PortfolioOptimizationAgent(
            event_store=self._event_store,
        )
        self.regime_detection = RegimeDetectionAgent(
            event_store=self._event_store,
        )
        self.alert = AlertAgent(event_store=self._event_store)
        self.reconciliation = ReconciliationAgent(
            event_store=self._event_store,
        )

        if market_data_provider is not None:
            from src.connectors.backtest_provider import BacktestDataProvider
            bt_provider = BacktestDataProvider(
                market_data_provider=market_data_provider,
                instruments=self.market_intel._instruments,
                exchange="NSE",
            )
        else:
            bt_provider = None

        self.reflection = ReflectionEngineAgent(
            event_store=self._event_store,
            backtest_data_provider=bt_provider,
        )
        self.personas = ExpertPersonasAgent(
            event_store=self._event_store,
            alternative_data_provider=None, # Will auto-init
            poll_interval=3600,
        )
        self._agents = [
            self.market_intel,
            self.strategy_gen,
            self.risk_mgmt,
            self.execution,
            self.portfolio_opt,
            self.regime_detection,
            self.alert,
            self.reconciliation,
            self.reflection,
            self.personas,
        ]
        for agent in self._agents:
            agent.system = self

    async def start(self) -> None:
        from src.risk.kill_switch import KillSwitch
        KillSwitch().setup(
            daily_loss_pct=settings.kill_switch_daily_loss_pct,
            max_drawdown_pct=settings.kill_switch_max_drawdown_pct,
            initial_capital=settings.reflection_initial_capital,
            auto_reset=settings.kill_switch_auto_reset,
        )

        if self._kite_client is not None:
            try:
                await self._kite_client.connect()
                if not self._kite_client.is_connected:
                    raise ConnectionError(
                        self._kite_client.connection_error or "Kite connection failed"
                    )
            except Exception as e:
                _logger = logging.getLogger("system")
                _logger.warning(
                    "Broker connection failed, falling back to paper trading: %s", e,
                )
                self._kite_broker = None
                self.execution._paper_trading = True
                self.execution._broker = None
        for agent in self._agents:
            await agent.start()

    def add_instrument(self, instrument: str) -> None:
        self.market_intel.add_instrument(instrument)

    def set_watchlist(self, instruments: list[str]) -> None:
        for inst in instruments:
            self.market_intel.add_instrument(inst)

    async def stop(self) -> None:
        _logger = logging.getLogger("system")
        _logger.info("Stopping trading system gracefully...")

        # 1. Stop execution agent first to cancel open orders and close positions
        if hasattr(self, "execution") and self.execution in self._agents:
            _logger.info("Stopping Execution Agent and running cleanup...")
            await self.execution.stop()

        # 2. Stop all other agents in reverse order
        for agent in reversed(self._agents):
            if agent.name != "execution":
                await agent.stop()

        # 3. Disconnect event store and clients
        await self._event_store.disconnect()
        if self._kite_client is not None:
            await self._kite_client.disconnect()
        _logger.info("Trading system stopped.")

    async def run_forever(self) -> None:
        loop = asyncio.get_event_loop()
        for sig_id in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig_id, lambda: asyncio.create_task(self.stop()))
            except NotImplementedError:
                pass

        print("Trading system running. Press Ctrl+C to stop.")
        await asyncio.gather(
            *(agent.run_forever() for agent in self._agents),
            return_exceptions=True,
        )

    async def health(self) -> dict[str, Any]:
        return {agent.name: await agent.health() for agent in self._agents}

    async def inject_tick(
        self,
        instrument: str,
        price: float,
        volume: int = 0,
        exchange: str = "NSE",
    ) -> None:
        from src.schemas.events import Exchange as Ex
        await self.market_intel.ingest_tick(
            instrument=instrument,
            exchange=Ex(exchange),
            last_price=price,
            volume=volume,
        )

    async def inject_ohlcv(
        self,
        instrument: str,
        interval: str,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        exchange: str = "NSE",
    ) -> None:
        from src.schemas.events import Exchange as Ex
        await self.market_intel.ingest_ohlcv(
            instrument=instrument,
            exchange=Ex(exchange),
            interval=interval,
            open=open,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
