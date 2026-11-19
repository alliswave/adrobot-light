"""Запуск миграций с теми же настройками, что и сервер."""

from alembic import context

from app.database import database_engine
from app.models import Base
from app.settings import DatabaseSettings

settings = DatabaseSettings()


def run_migrations() -> None:
    """Выбирает соединение с PostgreSQL или вывод SQL."""
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url.get_secret_value(),
            target_metadata=Base.metadata,
            literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = database_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
