from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(default="")
    telegram_webhook_secret: str = Field(default="")
    demo_mode: bool = True
    public_base_url: AnyUrl | None = None

    odoo_base_url: AnyUrl = "https://abmapex.ru"
    odoo_database: str = ""
    odoo_api_style: Literal["auto", "json2", "xmlrpc"] = "auto"
    odoo_api_key: str = ""
    odoo_username: str = ""
    odoo_password: str = ""
    odoo_default_user_id: int = 0
    odoo_verify_ssl: bool = True

    openai_api_key: str = ""
    ai_model: str = "gpt-5.1-mini"

    database_url: str = "postgresql+asyncpg://abm_bot:abm_bot@localhost:5432/abm_bot"
    app_env: Literal["local", "stage", "prod"] = "local"
    log_level: str = "INFO"
    timezone: str = "Asia/Yekaterinburg"


@lru_cache
def get_settings() -> Settings:
    return Settings()

