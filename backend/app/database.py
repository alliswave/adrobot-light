"""Пул подключений к PostgreSQL."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.settings import DatabaseSettings


def database_engine(settings: DatabaseSettings) -> Engine:
    """Открывает пул подключений к настроенной базе данных."""
    return create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
