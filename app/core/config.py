from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import field_validator
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

    database_url: str = "sqlite+aiosqlite:///./local.db"
    redis_url: str = "fakeredis://local"
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

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        url = value.strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

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
    def token_encryption_key_effective(self) -> str:
        value = self.bot_token_encryption_key.strip()
        if value:
            return value
        # Minimal mode fallback: deterministic key from master token.
        raw = hashlib.sha256((self.master_bot_token + "|tbm-minimal").encode("utf-8")).digest()
        return base64.urlsafe_b64encode(raw).decode("utf-8")

    @property
    def celery_broker(self) -> str:
        if self.celery_broker_url:
            return self.celery_broker_url
        if self.redis_url.startswith("fakeredis://"):
            return "memory://"
        return self.redis_url

    @property
    def celery_backend(self) -> str:
        if self.celery_result_backend:
            return self.celery_result_backend
        if self.redis_url.startswith("fakeredis://"):
            return "cache+memory://"
        return self.redis_url

    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "")

    @staticmethod
    def _contains_placeholder(value: str, placeholders: tuple[str, ...]) -> bool:
        lowered = value.lower()
        return any(marker.lower() in lowered for marker in placeholders)

    def preflight_checks(self) -> dict:
        checks: list[dict] = []

        def add(name: str, ok: bool, details: str, advisory: bool = False) -> None:
            checks.append({"name": name, "ok": ok, "details": details, "advisory": advisory})

        token = self.master_bot_token.strip()
        add("master_bot_token_set", bool(token), "MASTER_BOT_TOKEN must be set.")
        add(
            "master_bot_token_not_placeholder",
            bool(token) and "MASTER_BOT_TOKEN_FROM_BOTFATHER" not in token,
            "MASTER_BOT_TOKEN must be a real token from BotFather.",
        )

        add(
            "master_admin_ids_parsed",
            len(self.admin_id_set) > 0,
            "Optional in minimal mode. If empty, bootstrap mode allows first admin access.",
            advisory=True,
        )

        webhook = (self.webhook_base_url or "").strip()
        add(
            "webhook_base_url_https",
            webhook == "" or webhook.startswith("https://"),
            "Optional in minimal mode. Keep empty to use polling; set https:// URL for webhooks.",
        )
        add(
            "webhook_base_url_not_placeholder",
            webhook == "" or not self._contains_placeholder(webhook, ("your-railway-public-domain", "example")),
            "If set, WEBHOOK_BASE_URL should be your real Railway public domain.",
        )

        db_url = self.database_url.strip()
        add("database_url_set", bool(db_url), "DATABASE_URL must be set.")
        add(
            "database_url_not_localhost",
            db_url.startswith("sqlite+") or not self._contains_placeholder(db_url, ("localhost", "127.0.0.1")),
            "Minimal mode accepts sqlite. Otherwise use Railway Postgres (not localhost).",
        )
        add(
            "database_url_asyncpg",
            db_url.startswith("sqlite+") or "+asyncpg" in db_url,
            "Postgres mode should use postgresql+asyncpg:// (sqlite allowed in minimal mode).",
        )

        redis_url = self.redis_url.strip()
        add("redis_url_set", bool(redis_url), "REDIS_URL must be set.")
        add(
            "redis_url_not_localhost",
            redis_url.startswith("fakeredis://")
            or not self._contains_placeholder(redis_url, ("localhost", "127.0.0.1")),
            "Minimal mode accepts fakeredis. Otherwise use Railway Redis (not localhost).",
        )

        source = "derived"
        try:
            Fernet(self.token_encryption_key_effective.encode("utf-8"))
            fernet_ok = True
            if self.bot_token_encryption_key.strip():
                source = "env"
        except Exception:
            fernet_ok = False
        add(
            "bot_token_encryption_key_valid",
            fernet_ok,
            f"BOT_TOKEN_ENCRYPTION_KEY must be a valid Fernet key (source={source}).",
        )

        ops_key = (self.ops_api_key or "").strip()
        add(
            "ops_api_key_set",
            bool(ops_key),
            "Optional in minimal mode; required for /ops endpoints.",
            advisory=True,
        )

        return {
            "ok": all(item["ok"] for item in checks if not item["advisory"]),
            "checks": checks,
        }

    def validate_runtime(self) -> None:
        missing = []
        if not self.master_bot_token:
            missing.append("MASTER_BOT_TOKEN")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variables: {joined}")
        try:
            Fernet(self.token_encryption_key_effective.encode("utf-8"))
        except Exception as exc:
            raise RuntimeError("BOT_TOKEN_ENCRYPTION_KEY is invalid. Use Fernet.generate_key().") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
