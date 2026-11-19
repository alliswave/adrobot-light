"""Создание локальных учётных записей и вход оператора."""

from pydantic import BaseModel, SecretStr, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from app.repositories.users import UserRepository
from app.services.passwords import hash_password, password_matches
from app.settings import USERNAME_MAX_LENGTH

PASSWORD_MAX_LENGTH = 1024


class Credentials(BaseModel):
    """Единые правила для создания учётной записи и входа."""

    username: str
    password: SecretStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """Проверяет длину логина и совместимость с PostgreSQL и формой входа."""
        username = value.strip()
        if not 1 <= len(username) <= USERNAME_MAX_LENGTH:
            raise PydanticCustomError(
                "username_length", f"Логин должен содержать от 1 до {USERNAME_MAX_LENGTH} символов."
            )
        if any(character in username for character in ("\x00", "\r", "\n")):
            raise PydanticCustomError("username_character", "Логин содержит недопустимый символ.")
        return username

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        """Проверяет длину пароля без изменения введённых символов."""
        if not 1 <= len(value) <= PASSWORD_MAX_LENGTH:
            raise PydanticCustomError(
                "password_length",
                f"Пароль должен содержать от 1 до {PASSWORD_MAX_LENGTH} символов.",
            )
        return value


def create_user(users: UserRepository, username: str, password: str) -> None:
    """Проверяет данные и сохраняет нового оператора с хешем пароля."""
    try:
        credentials = Credentials(username=username, password=SecretStr(password))
    except ValidationError as exc:
        raise ValueError(exc.errors(include_input=False)[0]["msg"]) from exc
    users.add(credentials.username, hash_password(password))


def authenticate(users: UserRepository, credentials: Credentials) -> str | None:
    """Возвращает сохранённый логин после успешной проверки пароля."""
    record = users.find_credentials(credentials.username)
    password_hash = record.password_hash if record is not None else None
    if password_matches(credentials.password.get_secret_value(), password_hash):
        return record.username if record is not None else None
    return None
