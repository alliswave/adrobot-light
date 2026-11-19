"""Проверки редактора через FastAPI, PostgreSQL и HTTP-подмену Keitaro."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import JsonValue, SecretStr
from sqlalchemy import delete, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import database_engine
from app.main import create_app
from app.models import KnownStreamOffer
from app.repositories.users import UserRepository
from app.settings import DatabaseSettings, Settings
from app.use_cases.accounts import create_user

ORIGIN = "https://wrapper.example"
HEADERS = {"X-Requested-With": "KeitaroWrapper", "Origin": ORIGIN}
CATALOG = "/api/campaigns"
STREAMS = "/api/campaigns/42/streams"
PUBLISH = f"{STREAMS}/89/offers"
PREVIEW = "/api/offer-shares/preview"
OFFER_NAMES = {3717: "Первый", 3749: "Второй", 11111: "Третий", 11112: "Четвёртый", 11113: "Пятый"}
STREAM_SETTINGS: dict[str, JsonValue] = {
    "id": 89,
    "campaign_id": 42,
    "name": "Остальные страны",
    "type": "default",
    "schema": "landings",
    "state": "active",
    "collect_clicks": True,
    "comments": "Ручные настройки",
    "filters": [{"name": "country", "mode": "accept", "payload": ["US"]}],
    "landings": [{"landing_id": 7, "share": 100, "state": "active"}],
}
REDIRECT: dict[str, JsonValue] = {
    "id": 88,
    "campaign_id": 42,
    "name": "Перенаправление",
    "schema": "redirect",
    "action_payload": "https://google.com",
}


def binding(offer_id: int, share: int, *, state: str = "active") -> dict[str, JsonValue]:
    """Формирует ожидаемый формат привязки в Admin API."""
    return {"offer_id": offer_id, "share": share, "state": state}


@dataclass
class EditorTracker:
    """Подмена Admin API с независимым состоянием каталога и привязок."""

    offers: list[dict[str, JsonValue]] = field(
        default_factory=lambda: [binding(3717, 33), binding(3749, 33), binding(11112, 34)]
    )
    offer_names: dict[int, str] = field(default_factory=lambda: OFFER_NAMES.copy())
    stream_settings: dict[str, JsonValue] = field(default_factory=lambda: STREAM_SETTINGS.copy())
    other_streams: list[dict[str, JsonValue]] = field(default_factory=list)
    offsets: list[int] = field(default_factory=list)
    received: list[tuple[str, str]] = field(default_factory=list)
    writes: list[dict[str, JsonValue]] = field(default_factory=list)
    failure: Literal["refused", "no_response", "wrong_confirmation"] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Отвечает на чтение, принимает частичное обновление и моделирует сбои."""
        assert request.headers["Api-Key"] == "test-key"
        path = request.url.path.removeprefix("/admin_api/v1/")
        self.received.append((request.method, path))
        if request.method == "PUT":
            assert path == "streams/89"
            return self.update_stream(request)
        assert request.method == "GET"
        if path == "campaigns":
            offset = int(request.url.params["offset"])
            assert int(request.url.params["limit"]) >= 2
            self.offsets.append(offset)
            campaigns = [
                {"id": 14, "name": "Старая кампания"},
                {"id": 42, "name": "Создана в Keitaro"},
            ]
            return httpx.Response(200, json=campaigns[offset : offset + 1])
        if path == "offers":
            return httpx.Response(
                200, json=[{"id": key, "name": name} for key, name in self.offer_names.items()]
            )
        stream = {**self.stream_settings, "offers": self.offers}
        if path == "campaigns/42/streams":
            return httpx.Response(200, json=[REDIRECT, stream, *self.other_streams])
        if path == "streams/89":
            return httpx.Response(200, json=stream)
        if path == "streams/88":
            return httpx.Response(200, json=REDIRECT)
        return httpx.Response(404)

    def update_stream(self, request: httpx.Request) -> httpx.Response:
        """Применяет только полученные поля и подтверждает обновление."""
        payload = json.loads(request.content)
        self.writes.append(payload)
        if self.failure == "refused":
            return httpx.Response(406, json={"detail": "raw tracker message"})
        self.offers = list(payload["offers"])
        changed_settings = {key: value for key, value in payload.items() if key != "offers"}
        self.stream_settings.update(changed_settings)
        if self.failure == "no_response":
            raise httpx.ReadTimeout("Ответ потерян", request=request)
        confirmed = self.offers
        if self.failure == "wrong_confirmation":
            confirmed = self.offers[:-1]
        return httpx.Response(200, json={**self.stream_settings, "offers": confirmed})


@pytest.fixture(scope="module")
def editor_operator(test_database_url: str) -> None:
    """Создаёт отдельную учётную запись редактора в тестовой базе."""
    engine = database_engine(DatabaseSettings(database_url=SecretStr(test_database_url)))
    try:
        create_user(UserRepository(engine), "editor-operator", "local-test-password")
    finally:
        engine.dispose()


@pytest.fixture
def editor_tracker() -> EditorTracker:
    """Создаёт подмену с исходными привязками."""
    return EditorTracker()


@pytest.fixture
def editor_app(settings: Settings, editor_tracker: EditorTracker) -> FastAPI:
    """Запускает обычные маршруты приложения с локальной HTTP-подменой."""
    return create_app(settings, transport=httpx.MockTransport(editor_tracker))


@pytest.fixture
def editor_client(editor_app: FastAPI, editor_operator: None) -> Iterator[TestClient]:
    """Входит через API, после прогона очищает историю тестовых потоков."""
    with TestClient(editor_app, base_url=ORIGIN) as client:
        try:
            response = client.post(
                "/api/session",
                headers=HEADERS,
                json={"username": "editor-operator", "password": "local-test-password"},
            )
            assert response.status_code == 200
            yield client
        finally:
            with Session(editor_app.state.engine) as database, database.begin():
                database.execute(delete(KnownStreamOffer))


def put_draft(
    client: TestClient, ids: list[int], pinned: dict[int, int] | None = None
) -> httpx.Response:
    """Публикует черновик через защищённый маршрут."""
    body = {"offer_ids": ids, "pinned_shares": pinned or {}}
    response: httpx.Response = client.put(PUBLISH, headers=HEADERS, json=body)
    return response


def stream_rows(response: httpx.Response) -> list[dict[str, JsonValue]]:
    """Извлекает строки потока с офферами из успешного ответа загрузки."""
    assert response.status_code == 200, response.text
    assert response.json()[0] == {
        "id": 88,
        "name": "Перенаправление",
        "kind": "redirect",
        "offers": [],
    }
    rows: list[dict[str, JsonValue]] = response.json()[1]["offers"]
    return rows


def test_catalog_and_streams_read_actual_shares(
    editor_client: TestClient, editor_tracker: EditorTracker
) -> None:
    """Находит внешнюю кампанию на второй странице и показывает исходные доли."""
    assert editor_client.get(CATALOG).json() == [
        {"id": 14, "name": "Старая кампания"},
        {"id": 42, "name": "Создана в Keitaro"},
    ]
    assert editor_tracker.offsets == [0, 1, 2]
    rows = stream_rows(editor_client.get(STREAMS))
    assert [(row["id"], row["name"], row["share"]) for row in rows] == [
        (3717, "Первый", 33),
        (3749, "Второй", 33),
        (11112, "Четвёртый", 34),
    ]
    assert editor_tracker.writes == []


def test_preview_publish_and_reload_agree(
    editor_client: TestClient, editor_tracker: EditorTracker
) -> None:
    """Сверяет доли по ID на границах предпросмотра, записи и повторной загрузки."""
    stream_rows(editor_client.get(STREAMS))
    ids = [3717, 3749, 11112, 11111]
    draft = {"offer_ids": ids, "pinned_shares": {}}
    requests_before_preview = editor_tracker.received.copy()
    preview = editor_client.post(PREVIEW, headers=HEADERS, json=draft)

    assert preview.json() == {"3717": 25, "3749": 25, "11112": 25, "11111": 25}
    assert editor_tracker.received == requests_before_preview
    assert editor_tracker.offers == [binding(3717, 33), binding(3749, 33), binding(11112, 34)]
    assert editor_client.put(PUBLISH, headers=HEADERS, json=draft).status_code == 200
    assert editor_tracker.writes == [{"offers": [binding(offer_id, 25) for offer_id in ids]}]
    rows = stream_rows(editor_client.get(STREAMS))
    assert [(row["id"], row["share"]) for row in rows] == [(offer_id, 25) for offer_id in ids]
    assert editor_tracker.stream_settings == STREAM_SETTINGS


def test_zero_share_can_be_pinned_and_published(
    editor_client: TestClient, editor_tracker: EditorTracker
) -> None:
    """Сохраняет активный оффер с закреплёнными 0% при добавлении нового оффера."""
    editor_tracker.offers = [binding(3717, 0), binding(3749, 100)]
    loaded = stream_rows(editor_client.get(STREAMS))
    assert loaded[0] == {"id": 3717, "name": "Первый", "share": 0, "state": "active"}
    draft = {"offer_ids": [3717, 3749, 11112], "pinned_shares": {"3717": 0}}

    preview = editor_client.post(PREVIEW, headers=HEADERS, json=draft)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {"3717": 0, "3749": 50, "11112": 50}
    published = editor_client.put(PUBLISH, headers=HEADERS, json=draft)
    assert published.status_code == 200, published.text
    assert editor_tracker.writes == [
        {"offers": [binding(3717, 0), binding(3749, 50), binding(11112, 50)]}
    ]
    assert stream_rows(editor_client.get(STREAMS)) == published.json()["offers"]


@pytest.mark.parametrize("ambiguous_key", ["03717", "+3717", " 3717", "3717.0"])
def test_rejects_ambiguous_pin_keys_before_contacting_tracker(
    editor_client: TestClient, editor_tracker: EditorTracker, ambiguous_key: str
) -> None:
    """Отклоняет разные записи одного ID вместо подмены закреплённой доли."""
    draft = {"offer_ids": [3717, 3749], "pinned_shares": {"3717": 25, ambiguous_key: 50}}
    assert editor_client.post(PREVIEW, headers=HEADERS, json=draft).status_code == 422
    assert editor_client.put(PUBLISH, headers=HEADERS, json=draft).status_code == 422
    assert editor_tracker.received == []


def test_external_removal_history_and_pinned_restore(
    editor_client: TestClient, editor_tracker: EditorTracker, editor_app: FastAPI
) -> None:
    """Архивирует удалённые привязки и восстанавливает одну с сохранением долей и названий."""
    other_stream: dict[str, JsonValue] = {
        **STREAM_SETTINGS,
        "id": 90,
        "name": "Второй поток",
        "offers": [binding(3749, 100)],
    }
    editor_tracker.other_streams.append(other_stream)
    editor_tracker.offers = [binding(offer_id, 25) for offer_id in [3717, 3749, 11111, 11112]]
    stream_rows(editor_client.get(STREAMS))
    editor_tracker.offers = [binding(3717, 25), binding(11112, 25)]
    del editor_tracker.offer_names[3749]

    archived = stream_rows(editor_client.get(STREAMS))
    assert [(row["id"], row["share"], row["state"]) for row in archived] == [
        (3717, 25, "active"),
        (11112, 25, "active"),
        (3749, 0, "archived"),
        (11111, 0, "archived"),
    ]
    assert archived[2]["name"] == "Второй"
    response = put_draft(editor_client, [3717, 11112, 3749], {3717: 25})
    assert response.status_code == 200
    assert editor_tracker.writes == [
        {"offers": [binding(3717, 25), binding(11112, 37), binding(3749, 38)]}
    ]
    actual = editor_client.get(STREAMS)
    reloaded = stream_rows(actual)
    assert response.json()["offers"] == reloaded
    assert [(row["id"], row["name"], row["share"], row["state"]) for row in reloaded] == [
        (3717, "Первый", 25, "active"),
        (11112, "Четвёртый", 37, "active"),
        (3749, "Второй", 38, "active"),
        (11111, "Третий", 0, "archived"),
    ]
    assert actual.json()[2]["offers"] == [
        {"id": 3749, "name": "Второй", "share": 100, "state": "active"}
    ]
    assert editor_tracker.stream_settings == STREAM_SETTINGS
    with Session(editor_app.state.engine) as database:
        known = database.scalars(
            select(KnownStreamOffer).order_by(KnownStreamOffer.stream_id, KnownStreamOffer.offer_id)
        )
        assert [(row.stream_id, row.offer_id) for row in known] == [
            (89, 3717),
            (89, 3749),
            (89, 11111),
            (89, 11112),
            (90, 3749),
        ]


def test_disabled_binding_survives_publication(
    editor_client: TestClient, editor_tracker: EditorTracker
) -> None:
    """Отклоняет повторное добавление отключённого оффера и сохраняет его при записи."""
    editor_tracker.offers = [binding(3717, 60), binding(3749, 40)]
    assert stream_rows(editor_client.get(STREAMS))[1]["state"] == "active"
    editor_tracker.offers[1] = binding(3749, 40, state="disabled")
    refused = put_draft(editor_client, [3717, 3749])
    assert refused.status_code == 422
    assert "Отключённый" in refused.json()["detail"]
    assert editor_tracker.writes == []

    current = stream_rows(editor_client.get(STREAMS))
    assert current[1] == {"id": 3749, "name": "Второй", "share": 40, "state": "disabled"}
    published = put_draft(editor_client, [3717, 11112])
    assert published.status_code == 200
    assert editor_tracker.writes == [
        {"offers": [binding(3717, 50), binding(11112, 50), binding(3749, 40, state="disabled")]}
    ]
    assert stream_rows(editor_client.get(STREAMS))[2] == current[1]
    editor_tracker.offers.pop()
    assert stream_rows(editor_client.get(STREAMS))[2]["state"] == "archived"
    editor_tracker.offers.append(binding(3749, 40, state="disabled"))
    assert stream_rows(editor_client.get(STREAMS))[2:] == [current[1]]


def test_write_guards_preserve_tracker(
    editor_client: TestClient, editor_tracker: EditorTracker
) -> None:
    """Проверяет отсутствие записи при неверном потоке, долях и источнике запроса."""
    body = {"offer_ids": [3717], "pinned_shares": {}}
    for path, status in [
        ("/api/campaigns/14/streams/89/offers", 404),
        (f"{STREAMS}/999/offers", 404),
        (f"{STREAMS}/88/offers", 422),
    ]:
        assert editor_client.put(path, headers=HEADERS, json=body).status_code == status
    for headers in ({}, HEADERS | {"Origin": "https://foreign.example"}):
        assert editor_client.put(PUBLISH, headers=headers, json=body).status_code == 403
        assert editor_client.post(PREVIEW, headers=headers, json=body).status_code == 403
    duplicate = put_draft(editor_client, [3717, 3717])
    assert duplicate.status_code == 422
    assert "дважды" in duplicate.json()["detail"]
    assert put_draft(editor_client, [3717, 3749], {3717: 100}).status_code == 422
    assert editor_tracker.writes == []


def test_editor_routes_require_login(editor_app: FastAPI, editor_tracker: EditorTracker) -> None:
    """Проверяет, что анонимные запросы не доходят до трекера."""
    with TestClient(editor_app, base_url=ORIGIN) as client:
        assert client.get(CATALOG).status_code == 401
        assert client.get(STREAMS).status_code == 401
        body = {"offer_ids": [3717], "pinned_shares": {}}
        assert client.post(PREVIEW, headers=HEADERS, json=body).status_code == 401
        assert client.put(PUBLISH, headers=HEADERS, json=body).status_code == 401
    assert editor_tracker.received == []


@pytest.mark.parametrize("failure", ["refused", "no_response", "wrong_confirmation"])
def test_failed_publication_does_not_add_draft_to_history(
    editor_client: TestClient,
    editor_tracker: EditorTracker,
    editor_app: FastAPI,
    failure: Literal["refused", "no_response", "wrong_confirmation"],
) -> None:
    """Различает отказ и неизвестный исход, не сохраняет неподтверждённую привязку."""
    stream_rows(editor_client.get(STREAMS))
    editor_tracker.failure = failure
    response = put_draft(editor_client, [3717, 11113])
    assert response.status_code == 502
    detail = response.json()["detail"]
    if failure == "refused":
        assert detail["outcome_unknown"] is False
        assert "406" in detail["message"] and "raw tracker message" not in detail["message"]
        assert editor_tracker.offers == [binding(3717, 33), binding(3749, 33), binding(11112, 34)]
    else:
        assert detail["outcome_unknown"] is True
        assert "Сверьте результат" in detail["message"]
        assert editor_tracker.offers == [binding(3717, 50), binding(11113, 50)]
    assert len(editor_tracker.writes) == 1
    with Session(editor_app.state.engine) as database:
        assert database.get(KnownStreamOffer, (89, 11113)) is None


@pytest.mark.parametrize("failed_query", ["INSERT", "SELECT"])
def test_publication_confirms_tracker_write_even_when_history_fails(
    editor_client: TestClient,
    editor_tracker: EditorTracker,
    editor_app: FastAPI,
    failed_query: Literal["INSERT", "SELECT"],
) -> None:
    """Сообщает о принятой записи, а повторная загрузка восстанавливает локальную историю."""
    stream_rows(editor_client.get(STREAMS))

    history_queries: list[str] = []

    def fail_history_query(*args: object) -> None:
        """Прерывает запись архива или его чтение после успешной записи."""
        statement = str(args[2])
        if statement.startswith("INSERT INTO known_stream_offers"):
            operation = "INSERT"
        elif statement.startswith("SELECT known_stream_offers."):
            operation = "SELECT"
        else:
            return
        history_queries.append(operation)
        if operation == failed_query:
            raise OperationalError(statement, {}, Exception("Тестовый сбой истории"))

    event.listen(editor_app.state.engine, "before_cursor_execute", fail_history_query)
    try:
        response = put_draft(editor_client, [3717, 11113])
    finally:
        event.remove(editor_app.state.engine, "before_cursor_execute", fail_history_query)

    assert history_queries == (["INSERT", "SELECT"] if failed_query == "SELECT" else ["INSERT"])
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["outcome_unknown"] is False
    assert "Keitaro принял публикацию" in detail["message"]
    assert "Загрузите поток заново" in detail["message"]
    assert editor_tracker.writes == [{"offers": [binding(3717, 50), binding(11113, 50)]}]
    with Session(editor_app.state.engine) as database:
        assert database.get(KnownStreamOffer, (89, 11113)) is None
    reloaded = stream_rows(editor_client.get(STREAMS))
    assert reloaded[1] == {"id": 11113, "name": "Пятый", "share": 50, "state": "active"}
    with Session(editor_app.state.engine) as database:
        assert database.get(KnownStreamOffer, (89, 11113)) is not None
