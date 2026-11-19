"""Команды для управления локальными учётными записями."""

import argparse
from getpass import getpass

from app.database import database_engine
from app.repositories.users import UserRepository
from app.settings import DatabaseSettings
from app.use_cases.accounts import create_user


def main() -> None:
    """Создаёт оператора с паролем, введённым скрыто в терминале."""
    parser = argparse.ArgumentParser(description="Управление приложением Keitaro")
    commands = parser.add_subparsers(dest="command", required=True)
    user_command = commands.add_parser("create-user", help="Создать пользователя")
    user_command.add_argument("username", metavar="ЛОГИН")
    args = parser.parse_args()

    password = getpass("Пароль: ")
    if password != getpass("Повторите пароль: "):
        parser.exit(1, "Пароли не совпадают.\n")

    engine = database_engine(DatabaseSettings())
    try:
        create_user(UserRepository(engine), args.username, password)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    finally:
        engine.dispose()
    print("Пользователь создан.")


if __name__ == "__main__":
    main()
