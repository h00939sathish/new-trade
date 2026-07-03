from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    event_store_type: Literal["postgres", "sqlite", "memory"] = "sqlite"
    log_level: str = "INFO"

    postgres_dsn: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"

    redis_url: str = "redis://localhost:6379/0"

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""
    kite_user_id: str = ""

    groww_api_key: str = ""
    groww_api_secret: str = ""
    groww_totp_secret: str = ""
    groww_auth_token: str = ""

    angel_api_key: str = ""
    angel_client_id: str = ""
    angel_password: str = ""
    angel_totp: str = ""

    gemini_api_key: str = ""

    agent_market_intel_enabled: bool = True
    agent_strategy_gen_enabled: bool = True
    agent_risk_mgmt_enabled: bool = True
    agent_execution_enabled: bool = True
    agent_reflection_enabled: bool = True

    reflection_eval_window: int = 20
    reflection_initial_capital: float = 1_000_000.0

    risk_max_position_size: float = 100_000.0
    risk_max_drawdown_pct: float = 0.15
    risk_max_leverage: float = 3.0
    risk_max_order_value: float = 50_000.0
    risk_per_trade_loss_cap_pct: float = 0.01
    risk_max_open_positions: int = 5

    live_trading_enabled: bool = False
    broker_order_poll_interval_seconds: float = 5.0
    risk_require_volume_data: bool = False

    kill_switch_daily_loss_pct: float = 0.01
    kill_switch_max_drawdown_pct: float = 0.05
    kill_switch_auto_reset: bool = False

    consensus_threshold: float = 0.65
    consensus_short_threshold: float = 0.70
    signal_cooldown_seconds: int = 120

    reflection_mutation_enabled: bool = False
    reflection_require_human_approval: bool = True
    reflection_approval_timeout_hours: int = 72
    reflection_backtest_gate_threshold: float = 0.0
    earnings_calendar_path: str = "config/earnings_calendar.yaml"

    timescaledb_enabled: bool = True
    risk_sizing_method: str = "fixed"  # "fixed" or "kelly"
    risk_tax_lot_method: str = "average_cost"  # "average_cost", "fifo", "lifo", "hifo", or "specific_id"
    vault_provider: str = ""  # "", "vault", or "aws"
    pagerduty_routing_key: str = ""
    pagerduty_enabled: bool = False
    http_auth_token: str = ""
    reconciliation_broker_url: str = ""
    reconciliation_timeout_seconds: float = 30.0
    rate_limit_global_per_second: int = 50
    rate_limit_per_symbol_per_second: int = 10
    rate_limit_queue_depth: int = 100

    portfolio_optimizer_regime: str = "risk_parity"
    portfolio_optimizer_max_weight: float = 0.40
    portfolio_optimizer_min_weight: float = 0.05
    portfolio_optimizer_rebalance_interval: int = 300

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"

    agent_alert_enabled: bool = True

    yahoo_poll_interval: int = 60
    market_hours_only: bool = True

    gold_etf_symbol: str = "GOLDBEES"
    gold_futures_mcx_symbol: str = "GOLD"
    mcx_lot_size_gold: int = 1

    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"
    oanda_enabled_instruments: str = "XAU_USD,EUR_USD"
    oanda_execution_mode: str = "internal_simulation"

    @model_validator(mode="after")
    def check_credential_age(self) -> "Settings":
        env_path = self.model_config.get("env_file", ".env")
        if isinstance(env_path, str):
            env_file = Path(env_path)
            if env_file.exists():
                from datetime import UTC, datetime

                age_days = (datetime.now(UTC) - datetime.fromtimestamp(env_file.stat().st_mtime, tz=UTC)).days
                if age_days > 90:
                    import logging

                    logging.getLogger("config.settings").warning(
                        ".env file is %d days old (>90). Credentials may need rotation. "
                        "See docs/security.md for rotation policy.",
                        age_days,
                    )
        return self

    @model_validator(mode="after")
    def load_vault_secrets(self) -> "Settings":
        if not self.vault_provider:
            return self

        try:
            from src.utils.vault import load_secure_secret

            sensitive_keys = [
                ("kite_api_key", "TRA_KITE_API_KEY"),
                ("kite_api_secret", "TRA_KITE_API_SECRET"),
                ("kite_access_token", "TRA_KITE_ACCESS_TOKEN"),
                ("kite_user_id", "TRA_KITE_USER_ID"),
                ("groww_api_key", "TRA_GROWW_API_KEY"),
                ("groww_api_secret", "TRA_GROWW_API_SECRET"),
                ("groww_totp_secret", "TRA_GROWW_TOTP_SECRET"),
                ("groww_auth_token", "TRA_GROWW_AUTH_TOKEN"),
                ("angel_api_key", "TRA_ANGEL_API_KEY"),
                ("angel_client_id", "TRA_ANGEL_CLIENT_ID"),
                ("angel_password", "TRA_ANGEL_PASSWORD"),
                ("angel_totp", "TRA_ANGEL_TOTP"),
                ("gemini_api_key", "TRA_GEMINI_API_KEY"),
                ("telegram_bot_token", "TRA_TELEGRAM_BOT_TOKEN"),
                ("telegram_chat_id", "TRA_TELEGRAM_CHAT_ID"),
                ("pagerduty_routing_key", "TRA_PAGERDUTY_ROUTING_KEY"),
            ]

            for attr, env_name in sensitive_keys:
                val = load_secure_secret(env_name)
                if val:
                    setattr(self, attr, val)
        except Exception as e:
            import logging

            logging.getLogger("config.settings").error(
                "Failed to load secure secrets from vault: %s", e
            )

        return self


settings = Settings()
