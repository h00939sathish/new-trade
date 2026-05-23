from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    event_store_type: Literal["postgres", "sqlite", "kafka", "memory"] = "sqlite"
    log_level: str = "INFO"

    postgres_dsn: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_group_id: str = "trading-system"

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
    agent_strategy_gen_enabled: bool = False
    agent_risk_mgmt_enabled: bool = True
    agent_execution_enabled: bool = False
    agent_reflection_enabled: bool = True

    reflection_eval_window: int = 20
    reflection_initial_capital: float = 1_000_000.0

    risk_max_position_size: float = 100_000.0
    risk_max_drawdown_pct: float = 0.15
    risk_max_leverage: float = 3.0
    risk_max_order_value: float = 50_000.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"

    agent_alert_enabled: bool = True


settings = Settings()
