"""Проверки локальных учётных записей, cookie и доступа к поиску."""

import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import manage
from app.database import database_engine
from app.main import create_app
from app.models import User
from app.settings import Settings

HEADERS = {"X-Requested-With": "KeitaroWrapper", "Origin": "https://wrapper.example"}
PASSWORD = "test-operator-password"


def catalog(request: httpx.Request) -> httpx.Response:
    """Отдаёт каталог, доступный только через сервер с ключом."""
    assert request.method == "GET"
    assert request.url.path == "/admin_api/v1/offers"
    assert request.headers["Api-Key"] == "test-key"
    return httpx.Response(
        200,
        json=[
            {"id": 3717, "name": "Австралия", "state": "active"},
            {"id": 3749, "name": "Новая Зеландия", "state": "active"},
            {"id": 5000, "name": "Австралия с архивом", "state": "deleted"},
        ],
    )


def test_two_local_accounts_and_logout(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Создаёт двух операторов командой и проверяет независимые сеансы и поиск."""
    monkeypatch.setattr(manage, "getpass", lambda _prompt: PASSWORD)
    for username in ("alice", "boris"):
        monkeypatch.setattr(sys, "argv", ["manage", "create-user", username])
        manage.main()

    with pytest.raises(SystemExit) as duplicate:
        manage.main()
    assert duplicate.value.code == 1

    engine = database_engine(settings)
    try:
        with Session(engine) as database:
            users = list(
                database.scalars(select(User).where(User.username.in_(("alice", "boris"))))
            )
            assert len(users) == 2
            assert all(user.password_hash.startswith("$argon2id$") for user in users)
            assert users[0].password_hash != users[1].password_hash
    finally:
        engine.dispose()

    app = create_app(settings, transport=httpx.MockTransport(catalog))
    url = "https://wrapper.example"
    with TestClient(app, base_url=url) as alice, TestClient(app, base_url=url) as boris:
        for client, username in ((alice, "alice"), (boris, "boris")):
            signed_in = client.post(
                "/api/session", headers=HEADERS, json={"username": username, "password": PASSWORD}
            )
            assert signed_in.status_code == 200
            assert signed_in.json() == {"username": username}
            cookie = signed_in.headers["Set-Cookie"].lower()
            assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
            assert "max-age=28800" in cookie
            assert PASSWORD not in cookie
            assert client.get("/api/session").json() == {"username": username}

        for query in ("авсТРАЛ", "3717"):
            for client in (alice, boris):
                reply = client.get("/api/offers", params={"q": query})
                assert reply.status_code == 200
                assert reply.json() == [{"id": 3717, "name": "Австралия"}]
        assert alice.get("/api/offers", params={"q": "несуществующий"}).json() == []

        assert alice.delete("/api/session").status_code == 403
        assert alice.get("/api/session").status_code == 200
        assert alice.delete("/api/session", headers=HEADERS).status_code == 204
        assert alice.get("/api/offers").status_code == 401
        assert boris.get("/api/offers").status_code == 200


def test_invalid_login_is_generic(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Возвращает одинаковый ответ для неверного пароля и неизвестного логина."""
    monkeypatch.setattr(sys, "argv", ["manage", "create-user", "existing-user"])
    monkeypatch.setattr(manage, "getpass", lambda _prompt: PASSWORD)
    manage.main()
    with TestClient(create_app(settings), base_url="https://wrapper.example") as client:
        for username in ("existing-user", "unknown-user"):
            response = client.post(
                "/api/session", headers=HEADERS, json={"username": username, "password": "wrong"}
            )
            assert response.status_code == 401
            assert response.json() == {"detail": "Неверный логин или пароль."}
            assert "Set-Cookie" not in response.headers
        cross_site = client.post(
            "/api/session",
            headers=HEADERS | {"Origin": "https://foreign.example"},
            json={"username": "existing-user", "password": PASSWORD},
        )
        assert cross_site.status_code == 403
        assert client.get("/api/session").status_code == 401


def test_cookie_signature_and_expiration(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отклоняет подменённую подпись и cookie с истёкшим сроком действия."""
    monkeypatch.setattr(sys, "argv", ["manage", "create-user", "expiring-user"])
    monkeypatch.setattr(manage, "getpass", lambda _prompt: PASSWORD)
    manage.main()
    timestamp = 500_000
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda _signer: timestamp)
    with TestClient(create_app(settings), base_url="https://wrapper.example") as client:
        response = client.post(
            "/api/session",
            headers=HEADERS,
            json={"username": "expiring-user", "password": PASSWORD},
        )
        assert response.status_code == 200
        cookie = client.cookies["keitaro_session"]
        prefix, signature = cookie.rsplit(".", 1)
        first_byte = "A" if signature[0] != "A" else "B"
        forged_cookie = f"{prefix}.{first_byte}{signature[1:]}"
        assert client.get("/api/session").status_code == 200
        assert (
            client.get(
                "/api/session", headers={"Cookie": f"keitaro_session={forged_cookie}"}
            ).status_code
            == 401
        )
        timestamp += settings.session_max_age + 1
        assert client.get("/api/session").status_code == 401


def test_nul_username_is_rejected_by_the_login_route(settings: Settings) -> None:
    """Отклоняет нулевой символ в логине до поиска записи в PostgreSQL."""
    with TestClient(create_app(settings), base_url="https://wrapper.example") as client:
        response = client.post(
            "/api/session",
            headers=HEADERS,
            json={"username": "before\x00after", "password": PASSWORD},
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "Проверьте данные формы."}
    assert "Set-Cookie" not in response.headers


def test_cli_and_login_accept_unicode_at_the_length_limits(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Учитывает число символов при создании пользователя и входе."""
    username = "🦉" * 100
    password = "🦉" * 1024
    monkeypatch.setattr(sys, "argv", ["manage", "create-user", username])
    monkeypatch.setattr(manage, "getpass", lambda _prompt: password)
    manage.main()

    with TestClient(create_app(settings), base_url="https://wrapper.example") as client:
        response = client.post(
            "/api/session", headers=HEADERS, json={"username": username, "password": password}
        )
    assert response.status_code == 200
    assert response.json() == {"username": username}
