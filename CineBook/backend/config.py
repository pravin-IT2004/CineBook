"""Application configuration loaded from environment variables / the project-level .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "CineBook"
    environment: str = "development"
    log_level: str = "INFO"

    # MongoDB
    mongo_url: str = "mongodb://127.0.0.1:27017"
    mongo_db_name: str = "cinebook"
    mongo_timeout_ms: int = 3000
    # auto = use multi-document transactions only when the server supports them (replica set / sharded)
    use_transactions: str = "auto"

    # Security
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # First-run administrator (created only if no user with this e-mail exists)
    admin_email: str = ""
    admin_password: str = ""
    admin_name: str = "CineBook Admin"

    # Networking
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    public_api_url: str = "http://127.0.0.1:8000"

    # Localisation
    app_timezone: str = "Asia/Kolkata"
    currency_symbol: str = "₹"

    # Optional e-mail confirmations (leave SMTP_HOST empty to disable)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # Background cleanup of expired seat holds / stuck bookings
    cleanup_interval_seconds: int = 60

    @field_validator("use_transactions")
    @classmethod
    def _tx_mode(cls, v: str) -> str:
        v = (v or "auto").strip().lower()
        if v not in {"auto", "true", "false"}:
            raise ValueError("USE_TRANSACTIONS must be auto, true or false")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_security(self) -> None:
        if len(self.jwt_secret or "") < 32 or self.jwt_secret.startswith("change-me"):
            raise RuntimeError(
                "JWT_SECRET is missing or too short (min 32 characters). "
                "Run 'python scripts/create_env.py' to generate a .env file with secure random secrets."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
