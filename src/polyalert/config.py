from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(..., min_length=10)
    polymarket_rest_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_wss_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    db_path: str = "./polyalert.db"
    max_alerts_per_user: int = 10
    wss_stale_timeout_seconds: int = 300
    owner_user_id: int | None = None  # Telegram user_id allowed to use /status
    log_level: str = "INFO"
