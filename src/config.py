"""Typed configuration loaded from .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bot configuration. All fields loaded from environment or .env file."""

    bot_token: str
    owner_user_id: int
    chat_id: int | None = None  # Auto-detected from first owner message if not set
    auth_token: str
    ipc_host: str = "0.0.0.0"
    ipc_port: int = 9800

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
