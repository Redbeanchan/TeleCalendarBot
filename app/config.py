from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: SecretStr
    telegram_allowed_user_id: int
    timezone: str = "Asia/Singapore"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:14b"
    ollama_timeout_seconds: float = 90
    ollama_num_threads: int = Field(default=4, ge=1)
    ollama_num_ctx: int = Field(default=2048, ge=512)
    ollama_num_gpu: int = Field(default=-1, ge=-1)
    database_path: Path = Path("data/assistant.db")
    google_calendar_id: str = "primary"
    google_credentials_path: Path = Path("secrets/google_credentials.json")
    google_token_path: Path = Path("secrets/google_token.json")
    pending_action_ttl_minutes: int = 30
    reminder_poll_seconds: int = Field(default=15, ge=5)
    calendar_reminders_enabled: bool = True
    calendar_reminder_minutes: int = Field(default=30, ge=1)
    calendar_poll_seconds: int = Field(default=300, ge=60)
    log_level: str = "INFO"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def local_ollama_only(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_BASE_URL must be an HTTP(S) URL")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
