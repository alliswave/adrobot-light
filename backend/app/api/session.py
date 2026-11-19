"""Подписанный сеанс оператора и защита запросов браузера."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadData, URLSafeTimedSerializer

from app.settings import Settings

SESSION_COOKIE = "keitaro_session"


@dataclass(frozen=True)
class Operator:
    """Публичные данные текущего оператора."""

    username: str


@dataclass(frozen=True)
class BrowserSession:
    """Кодирует и проверяет сеанс, записанный в cookie."""

    settings: Settings
    signer: URLSafeTimedSerializer

    @classmethod
    def configure(cls, settings: Settings) -> BrowserSession:
        """Настраивает подпись cookie отдельной солью приложения."""
        return cls(
            settings,
            URLSafeTimedSerializer(settings.session_secret.get_secret_value(), salt="operator"),
        )

    def read(self, request: Request) -> Operator | None:
        """Читает данные оператора из действующей подписанной cookie."""
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie is None:
            return None
        try:
            username = self.signer.loads(cookie, max_age=self.settings.session_max_age)
        except BadData:
            return None
        return Operator(username) if isinstance(username, str) else None

    def write(self, request: Request, response: Response, operator: Operator) -> None:
        """Устанавливает cookie с ограниченным сроком действия."""
        response.set_cookie(
            SESSION_COOKIE,
            self.signer.dumps(operator.username),
            max_age=self.settings.session_max_age,
            httponly=True,
            secure=self.requires_secure_cookie(request),
            samesite="lax",
        )

    def clear(self, request: Request, response: Response) -> None:
        """Удаляет cookie оператора в браузере."""
        response.delete_cookie(
            SESSION_COOKIE,
            httponly=True,
            secure=self.requires_secure_cookie(request),
            samesite="lax",
        )

    def requires_secure_cookie(self, request: Request) -> bool:
        """Проверяет, должен ли браузер передавать cookie только по HTTPS."""
        return self.settings.session_secure or request.url.scheme == "https"


def browser_session(request: Request) -> BrowserSession:
    """Возвращает настроенный обработчик сеансов из состояния приложения."""
    session: BrowserSession = request.app.state.browser_session
    return session


SessionCookie = Annotated[BrowserSession, Depends(browser_session)]


def require_operator(request: Request, session: SessionCookie) -> Operator:
    """Запрещает доступ к операциям без действующего сеанса."""
    operator = session.read(request)
    if operator is None:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Войдите в приложение.")
    return operator


def require_same_origin_write(request: Request) -> None:
    """Проверяет заголовок запроса и источник, если он указан браузером."""
    origin = request.headers.get("Origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("X-Requested-With") != "KeitaroWrapper" or (
        origin is not None and origin != expected_origin
    ):
        raise HTTPException(
            HTTPStatus.FORBIDDEN, "Запрос отклонён. Откройте приложение и повторите действие."
        )
