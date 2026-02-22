from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Telegram Bot Maker"
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8000
    default_timezone: str = "UTC"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_platform"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    webhook_base_url: str | None = None
    master_bot_token: str = ""
    master_bot_webhook_secret: str = "master-webhook-secret"
    platform_brand_handle: str = "@PlatformBot"
    bot_token_encryption_key: str = ""
    master_admin_ids: str = ""
    ops_api_key: str | None = None

    broadcast_flood_sleep: float = 0.06
    broadcast_max_retries: int = 5
    broadcast_batch_size: int = 500

    @field_validator("webhook_base_url")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value:
            return value.rstrip("/")
        return value

    @property
    def admin_id_set(self) -> set[int]:
        if not self.master_admin_ids.strip():
            return set()
        parsed: set[int] = set()
        for item in self.master_admin_ids.split(","):
            item = item.strip()
            if item:
                try:
                    parsed.add(int(item))
                except ValueError:
                    continue
        return parsed

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "")

    def validate_runtime(self) -> None:
        missing = []
        if not self.master_bot_token:
            missing.append("MASTER_BOT_TOKEN")
        if not self.bot_token_encryption_key:
            missing.append("BOT_TOKEN_ENCRYPTION_KEY")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variables: {joined}")
        try:
            Fernet(self.bot_token_encryption_key.encode("utf-8"))
        except Exception as exc:
            raise RuntimeError("BOT_TOKEN_ENCRYPTION_KEY is invalid. Use Fernet.generate_key().") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
