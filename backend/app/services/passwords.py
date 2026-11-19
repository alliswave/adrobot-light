"""Хеширование и проверка паролей оператора."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_passwords = PasswordHasher()
# Проверка отсутствующего пользователя занимает столько же времени, сколько проверка пароля.
_missing_user_hash = _passwords.hash("missing user")


def hash_password(password: str) -> str:
    """Хеширует пароль с помощью Argon2."""
    return _passwords.hash(password)


def password_matches(password: str, password_hash: str | None) -> bool:
    """Проверяет пароль с фиктивным хешем при отсутствии учётной записи."""
    try:
        return (
            _passwords.verify(
                password_hash if password_hash is not None else _missing_user_hash, password
            )
            and password_hash is not None
        )
    except VerifyMismatchError:
        return False
