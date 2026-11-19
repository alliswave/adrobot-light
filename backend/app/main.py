"""Точка входа FastAPI и управление подключениями приложения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.keitaro import KeitaroClient
from app.api.routes import router
from app.api.session import BrowserSession
from app.database import database_engine
from app.repositories.stream_offer_history import StreamOfferHistoryRepository
from app.repositories.users import UserRepository
from app.settings import KEITARO_TIMEOUT_SECONDS, Settings

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    settings: Settings | None = None, *, transport: httpx.BaseTransport | None = None
) -> FastAPI:
    """Собирает приложение с подключениями к базе и Admin API."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Открывает и закрывает подключения при запуске и остановке."""
        configured = settings or Settings()
        engine = database_engine(configured)
        try:
            with httpx.Client(
                base_url=f"{str(configured.keitaro_url).rstrip('/')}/admin_api/v1/",
                timeout=KEITARO_TIMEOUT_SECONDS,
                transport=transport,
                follow_redirects=False,
            ) as http:
                app.state.engine = engine
                app.state.users = UserRepository(engine)
                app.state.stream_offer_history = StreamOfferHistoryRepository(engine)
                app.state.browser_session = BrowserSession.configure(configured)
                app.state.keitaro = KeitaroClient(http, configured)
                yield
        finally:
            engine.dispose()

    app = FastAPI(title="Adrobot Light", lifespan=lifespan)
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, validation_error)

    frontend_index = FRONTEND_DIST / "index.html"
    if frontend_index.is_file():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def frontend() -> FileResponse:
            """Отдаёт главную страницу собранного интерфейса Vue."""
            return FileResponse(frontend_index)

    return app


def validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Возвращает безопасное сообщение без исходных данных запроса."""
    return JSONResponse(
        {"detail": "Проверьте данные формы."}, status_code=HTTPStatus.UNPROCESSABLE_ENTITY
    )


app = create_app()
