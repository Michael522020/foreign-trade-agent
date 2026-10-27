"""运行时配置只读环境变量。示例配置文件不参与运行。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./var/dev.db"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
