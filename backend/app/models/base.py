"""Общие метаданные моделей PostgreSQL."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Общие метаданные таблиц приложения."""
