"""Настройки базы данных, сеансов и подключения к трекеру."""

from typing import Annotated

from pydantic import Field, HttpUrl, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
SESSION_SECRET_MIN_LENGTH = 32
USERNAME_MAX_LENGTH = 100
KEITARO_TIMEOUT_SECONDS = 10.0


class DatabaseSettings(BaseSettings):
    """Настройки, необходимые также для миграций и команды управления."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr


class Settings(DatabaseSettings):
    """Настройки сервера и подключения к Keitaro."""

    session_secret: Annotated[SecretStr, Field(min_length=SESSION_SECRET_MIN_LENGTH)]
    session_max_age: PositiveInt = SESSION_MAX_AGE_SECONDS
    session_secure: bool = False
    keitaro_url: HttpUrl
    keitaro_api_key: SecretStr
