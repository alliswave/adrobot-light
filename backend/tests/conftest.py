"""Тестовая база PostgreSQL и настройки сервера."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url

from app.settings import Settings


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Создаёт отдельную базу, применяет миграции и удаляет её после прогона."""
    server_url = make_url(os.environ["TEST_DATABASE_URL"])
    database_name = f"wrapper_test_{uuid4().hex}"
    migrated_url = server_url.set(database=database_name).render_as_string(hide_password=False)
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {database_name}")
        try:
            with pytest.MonkeyPatch.context() as env:
                env.setenv("DATABASE_URL", migrated_url)
                config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
                command.upgrade(config, "head")
            yield migrated_url
        finally:
            with admin.connect() as connection:
                connection.exec_driver_sql(f"DROP DATABASE {database_name} WITH (FORCE)")
    finally:
        admin.dispose()


@pytest.fixture
def settings(test_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Настраивает приложение на тестовую базу и локальную подмену трекера."""
    values = {
        "DATABASE_URL": test_database_url,
        "SESSION_SECRET": "local-test-session-secret-at-least-32-bytes",
        "KEITARO_URL": "https://tracker.example",
        "KEITARO_API_KEY": "test-key",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings()
