from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, Field, field_validator
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
    telegram_odoo_user_map: dict[int, int] = Field(default_factory=dict)
    telegram_invite_codes: dict[str, dict[str, int | str | bool]] = Field(default_factory=dict)
    odoo_project_ids: list[int] = Field(default_factory=list)
    odoo_scope_label: str = ""
    odoo_verify_ssl: bool = True
    odoo_include_blocker_text: bool = False

    ai_provider: Literal["auto", "openai", "yandex"] = "auto"
    openai_api_key: str = ""
    ai_model: str = "gpt-5-mini"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_ai_model: str = "aliceai-llm"

    pm_telegram_ids: str = ""
    tech_lead_telegram_ids: str = ""

    database_url: str = "postgresql+asyncpg://abm_bot:abm_bot@localhost:5432/abm_bot"
    app_env: Literal["local", "stage", "prod"] = "local"
    log_level: str = "INFO"
    timezone: str = "Asia/Yekaterinburg"

    @field_validator("public_base_url", mode="before")
    @classmethod
    def empty_optional_url_as_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ai_model", mode="before")
    @classmethod
    def empty_ai_model_as_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return "gpt-5-mini"
        return value

    @field_validator("yandex_ai_model", mode="before")
    @classmethod
    def empty_yandex_ai_model_as_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return "aliceai-llm"
        return value

    def odoo_user_id_for(self, telegram_user_id: int) -> int:
        return self.telegram_odoo_user_map.get(telegram_user_id, self.odoo_default_user_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
