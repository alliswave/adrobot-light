"""Чтение и создание учётных записей в PostgreSQL."""

from dataclasses import dataclass

from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User


class DuplicateUsernameError(ValueError):
    """Учётная запись с таким логином уже существует."""


@dataclass(frozen=True)
class StoredCredentials:
    """Сохранённый логин и хеш пароля для проверки при входе."""

    username: str
    password_hash: str


class UserRepository:
    """Управляет локальными учётными записями."""

    def __init__(self, engine: Engine) -> None:
        """Принимает общий пул PostgreSQL."""
        self._engine = engine

    def add(self, username: str, password_hash: str) -> None:
        """Сохраняет оператора и распознаёт конфликт уникальности логина."""
        with Session(self._engine) as database:
            database.add(User(username=username, password_hash=password_hash))
            try:
                database.commit()
            except IntegrityError as exc:
                if getattr(exc.orig, "sqlstate", None) == UniqueViolation.sqlstate:
                    raise DuplicateUsernameError("Этот логин уже занят.") from exc
                raise

    def find_credentials(self, username: str) -> StoredCredentials | None:
        """Ищет логин и хеш пароля, не выдавая наружу объект таблицы."""
        with Session(self._engine) as database:
            user = database.scalar(select(User).where(User.username == username))
            if user is None:
                return None
            return StoredCredentials(user.username, user.password_hash)
