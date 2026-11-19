"""Проверки записи кампании через FastAPI и границу HTTP Keitaro."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import JsonValue, SecretStr

from app.database import database_engine
from app.main import create_app
from app.repositories.users import UserRepository
from app.settings import DatabaseSettings, Settings
from app.use_cases.accounts import create_user

CREATE = "/admin_api/v1/campaigns"
STREAM = "/admin_api/v1/streams"
CAMPAIGN = "/admin_api/v1/campaigns/42"
ENABLE = f"{CAMPAIGN}/enable"
REQUESTS = [CREATE, STREAM, STREAM, ENABLE]
HEADERS = {"X-Requested-With": "KeitaroWrapper"}
FORM = {"name": "Campaign AU", "country": "AU", "offer_id": 3717}
PAYLOAD = FORM | {"group_id": 181, "traffic_source_id": 207}
REDIRECT_FIXTURE = Path(__file__).parent / "fixtures" / "redirect_stream.json"
NATIVE_REDIRECT_REQUEST = Path(__file__).parent / "fixtures" / "native_panel_redirect_request.json"
OFFER_STREAM_FIXTURE = Path(__file__).parent / "fixtures" / "offer_stream.json"


@dataclass
class Tracker:
    """HTTP-подмена, которая учитывает подтверждённые и принятые записи."""

    paths: list[str] = field(default_factory=list)
    bodies: list[dict[str, JsonValue] | None] = field(default_factory=list)
    fail_at: int | None = None
    rejection_reply: JsonValue = field(
        default_factory=lambda: dict[str, JsonValue](error="diagnostic should not appear")
    )
    lose_response_at: int | None = None
    omit_redirect_url: bool = False
    campaign_response: dict[str, JsonValue] | None = None
    enable_reply: httpx.Response | None = None
    campaign_read_reply: httpx.Response | None = None
    campaign_reads: list[str] = field(default_factory=list)
    redirect_changes: dict[str, JsonValue] = field(default_factory=dict)
    offer_stream_changes: dict[str, JsonValue] = field(default_factory=dict)
    state: str | None = None
    offer_stream_recorded: bool = False
    catalogs_read: list[str] = field(default_factory=list)
    groups: list[dict[str, JsonValue]] = field(default_factory=list)
    sources: list[dict[str, JsonValue]] = field(default_factory=list)
    catalog_failure: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Записывает запрос и возвращает ответ или имитирует потерю связи."""
        assert request.headers["Api-Key"] == "test-key"
        if request.method == "GET":
            if request.url.path == CAMPAIGN:
                assert self.paths == REQUESTS
                assert not request.url.params
                self.campaign_reads.append(request.url.path)
                return self.campaign_read_reply or httpx.Response(
                    200, json={"id": 42, "state": self.state}
                )
            return self.read_catalog(request)
        assert request.method == "POST"
        path = request.url.path
        self.paths.append(path)
        self.bodies.append(json.loads(request.content) if request.content else None)
        step = len(self.paths)
        assert path == REQUESTS[step - 1]
        if step == self.fail_at:
            return httpx.Response(406, json=self.rejection_reply)
        if step == 1:
            self.state = "disabled"
            reply = httpx.Response(
                200, json=self.campaign_response or {"id": 42, "state": self.state}
            )
        elif step == 2:
            stream: dict[str, JsonValue] = json.loads(REDIRECT_FIXTURE.read_text())
            if self.omit_redirect_url:
                del stream["action_payload"]
            reply = httpx.Response(200, json=stream | self.redirect_changes)
        elif step == 3:
            self.offer_stream_recorded = True
            offer_stream: dict[str, JsonValue] = json.loads(OFFER_STREAM_FIXTURE.read_text())
            reply = httpx.Response(200, json=offer_stream | self.offer_stream_changes)
        else:
            self.state = "active"
            reply = self.enable_reply or httpx.Response(200, json={"id": 42, "state": self.state})
        if step == self.lose_response_at:
            raise httpx.ReadTimeout("response lost", request=request)
        return reply

    def read_catalog(self, request: httpx.Request) -> httpx.Response:
        """Отдаёт текущее состояние справочника по нужному пути Admin API."""
        path = request.url.path
        self.catalogs_read.append(path)
        if path == "/admin_api/v1/groups":
            assert dict(request.url.params) == {"type": "campaigns"}
            entries = self.groups
        else:
            assert path == "/admin_api/v1/traffic_sources"
            assert not request.url.params
            entries = self.sources
        if path == self.catalog_failure:
            return httpx.Response(503, text="diagnostic should not appear")
        return httpx.Response(200, json=entries)


@pytest.fixture(scope="module")
def campaign_operator(test_database_url: str) -> None:
    """Создаёт оператора кампаний в мигрированной PostgreSQL."""
    engine = database_engine(DatabaseSettings(database_url=SecretStr(test_database_url)))
    try:
        create_user(UserRepository(engine), "campaign-operator", "local-test-password")
    finally:
        engine.dispose()


@pytest.fixture
def tracker() -> Tracker:
    """Создаёт независимую модель состояния внешнего трекера."""
    return Tracker()


@pytest.fixture
def campaign_app(settings: Settings, tracker: Tracker) -> FastAPI:
    """Подключает производственное приложение к подмене Admin API."""
    return create_app(settings, transport=httpx.MockTransport(tracker))


@pytest.fixture
def signed_in(campaign_app: FastAPI, campaign_operator: None) -> Iterator[TestClient]:
    """Входит через маршрут FastAPI и сохраняет cookie в клиенте."""
    with TestClient(campaign_app) as client:
        response = client.post(
            "/api/session",
            headers=HEADERS,
            json={"username": "campaign-operator", "password": "local-test-password"},
        )
        assert response.status_code == 200
        yield client


def test_campaign_options_are_live_and_public_fields_only(
    signed_in: TestClient, tracker: Tracker
) -> None:
    """При каждом чтении берёт новые данные и скрывает лишние поля и записи."""
    tracker.groups = [
        {"id": 181, "name": "Поиск", "type": "campaigns", "position": 1},
        {"id": 182, "name": "Неподходящая группа", "type": "offers"},
    ]
    tracker.sources = [
        {"id": 207, "name": "Поисковая реклама", "state": "active", "notes": "private"},
        {"id": 208, "name": "Удалённый", "state": "deleted"},
        {"id": 209, "name": "Архивный", "state": "archived"},
        {"id": 210, "name": "Без состояния"},
        {"id": 211, "name": "С неизвестным состоянием", "state": "unknown"},
        {"id": 212, "name": "С пустым состоянием", "state": None},
    ]
    response = signed_in.get("/api/campaign-options")
    assert response.status_code == 200
    assert response.json() == {
        "groups": [{"id": 181, "name": "Поиск"}],
        "traffic_sources": [{"id": 207, "name": "Поисковая реклама"}],
    }

    tracker.groups.append({"id": 183, "name": "Новая группа", "type": "campaigns"})
    tracker.sources[0]["state"] = "archived"
    refreshed = signed_in.get("/api/campaign-options")
    assert refreshed.status_code == 200
    assert refreshed.json() == {
        "groups": [{"id": 181, "name": "Поиск"}, {"id": 183, "name": "Новая группа"}],
        "traffic_sources": [],
    }
    assert tracker.catalogs_read == ["/admin_api/v1/groups", "/admin_api/v1/traffic_sources"] * 2
    assert tracker.paths == []


def test_campaign_options_require_authentication(campaign_app: FastAPI, tracker: Tracker) -> None:
    """Блокирует анонимное чтение справочников до обращения к Keitaro."""
    with TestClient(campaign_app) as client:
        response = client.get("/api/campaign-options")
    assert response.status_code == 401
    assert tracker.catalogs_read == []


@pytest.mark.parametrize("catalog", ["/admin_api/v1/groups", "/admin_api/v1/traffic_sources"])
def test_campaign_options_error_allows_fresh_read(
    signed_in: TestClient, tracker: Tracker, catalog: str
) -> None:
    """Возвращает безопасную ошибку вместо частичного ответа и перечитывает справочники."""
    tracker.catalog_failure = catalog
    failed = signed_in.get("/api/campaign-options")
    assert failed.status_code == 502
    assert failed.json() == {"detail": "Не удалось загрузить справочники из Keitaro."}
    tracker.catalog_failure = None

    response = signed_in.get("/api/campaign-options")
    assert response.status_code == 200
    assert response.json() == {"groups": [], "traffic_sources": []}
    assert tracker.paths == []


@pytest.mark.parametrize("country_payload", ['["AU"]', ["AU"]])
def test_creates_and_enables_campaign(
    signed_in: TestClient, tracker: Tracker, country_payload: JsonValue
) -> None:
    """Сверяет привязки, геофильтр, перенаправление, долю оффера и порядок записи."""
    tracker.redirect_changes = {
        "filters": [{"name": "country", "mode": "accept", "payload": country_payload}]
    }
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 201
    assert response.json() == {"id": 42, "name": "Campaign AU"}
    assert tracker.paths == REQUESTS
    campaign, redirect, offer_flow, enable = tracker.bodies
    assert campaign is not None
    alias = campaign.pop("alias")
    assert isinstance(alias, str) and re.fullmatch(r"campaign-au-[0-9a-f]{12}", alias)
    assert campaign == {
        "name": "Campaign AU",
        "group_id": "181",
        "traffic_source_id": 207,
        "state": "disabled",
        "type": "position",
    }
    # Фрагмент campaigns.create штатной панели. Запрос перехвачен до отправки.
    native_redirect: dict[str, JsonValue] = json.loads(NATIVE_REDIRECT_REQUEST.read_text())
    assert redirect == native_redirect | {
        "campaign_id": 42,
        "name": "AU → Google",
        "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
    }
    assert offer_flow == {
        "campaign_id": 42,
        "name": "Остальные страны",
        "schema": "landings",
        "type": "default",
        "action_type": "http",
        "position": 2,
        "state": "active",
        "offers": [{"offer_id": 3717, "share": 100, "state": "active"}],
    }
    assert enable is None
    assert tracker.state == "active"
    assert tracker.catalogs_read == []
    assert tracker.campaign_reads == []


@pytest.mark.parametrize(
    ("enable_status", "enable_body", "lose_response"),
    [
        pytest.param(200, b"{}", False, id="acknowledgement"),
        pytest.param(204, b"", False, id="empty-body"),
        pytest.param(200, b"{", False, id="invalid-json"),
        pytest.param(200, b'{"id": 42}', False, id="missing-state"),
        pytest.param(200, b'{"id": 42, "state": "disabled"}', False, id="stale-state"),
        pytest.param(200, b'{"id": 43, "state": "active"}', False, id="wrong-id"),
        pytest.param(503, b"", False, id="server-error"),
        pytest.param(200, b"", True, id="lost-response"),
    ],
)
def test_reads_active_campaign_after_inconclusive_enable(
    signed_in: TestClient,
    tracker: Tracker,
    enable_status: int,
    enable_body: bytes,
    lose_response: bool,
) -> None:
    """Считает включение успешным после одного чтения нужной активной кампании."""
    tracker.enable_reply = httpx.Response(enable_status, content=enable_body)
    if lose_response:
        tracker.lose_response_at = 4

    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 201
    assert response.json() == {"id": 42, "name": "Campaign AU"}
    assert tracker.paths == REQUESTS
    assert tracker.campaign_reads == [CAMPAIGN]


@pytest.mark.parametrize(
    ("enable_status", "read_status", "read_reply"),
    [
        pytest.param(200, 200, {"id": 42, "state": "disabled"}, id="disabled"),
        pytest.param(200, 200, {"id": 43, "state": "active"}, id="wrong-id"),
        pytest.param(200, 200, {"id": "42", "state": "active"}, id="non-integer-id"),
        pytest.param(200, 200, {"id": 42}, id="missing-state"),
        pytest.param(200, 200, None, id="invalid-body"),
        pytest.param(200, 503, {"id": 42, "state": "active"}, id="read-failed"),
        pytest.param(503, 404, {}, id="enable-failed-and-read-not-found"),
    ],
)
def test_enable_remains_uncertain_without_matching_active_campaign(
    signed_in: TestClient,
    tracker: Tracker,
    enable_status: int,
    read_status: int,
    read_reply: JsonValue,
) -> None:
    """Сохраняет неопределённый результат, если чтение его не подтверждает."""
    tracker.enable_reply = httpx.Response(enable_status, json={})
    tracker.campaign_read_reply = httpx.Response(read_status, json=read_reply)

    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == "enable"
    assert detail["campaign_id"] == 42
    assert detail["outcome_unknown"] is True
    assert detail["refresh_options"] is False
    assert "Проверьте результат в Keitaro" in detail["message"]
    if enable_status == 503:
        assert "HTTP 503" in detail["message"]
        assert "HTTP 404" not in detail["message"]
    assert tracker.paths == REQUESTS
    assert tracker.campaign_reads == [CAMPAIGN]


@pytest.mark.parametrize(
    ("patch",),
    [
        ({"name": "  "},),
        ({"country": "ZZ"},),
        ({"country": "AU US"},),
        ({"offer_id": True},),
        ({"offer_id": 0},),
        ({"group_id": "181"},),
        ({"group_id": 0},),
        ({"traffic_source_id": True},),
        ({"traffic_source_id": -1},),
    ],
)
def test_invalid_form_stops_before_writes(
    signed_in: TestClient, tracker: Tracker, patch: dict[str, object]
) -> None:
    """Отклоняет недопустимые данные до обращения к трекеру."""
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD | patch)

    assert response.status_code == 422
    assert tracker.paths == []


@pytest.mark.parametrize("selection", [{}, {"group_id": 181}, {"traffic_source_id": 207}])
def test_missing_campaign_options_stop_before_writes(
    signed_in: TestClient, tracker: Tracker, selection: dict[str, int]
) -> None:
    """Требует оба идентификатора, в том числе в запросе прежнего формата."""
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=FORM | selection)
    assert response.status_code == 422
    assert tracker.paths == []


def test_anonymous_creation_stops_before_writes(campaign_app: FastAPI, tracker: Tracker) -> None:
    """Возвращает 401 анонимному оператору до обращения к Keitaro."""
    with TestClient(campaign_app) as client:
        response = client.post("/api/campaigns", json=PAYLOAD)
    assert response.status_code == 401
    assert tracker.paths == []


@pytest.mark.parametrize("headers", [{}, HEADERS | {"Origin": "https://other.example"}])
def test_cross_site_creation_stops_before_writes(
    signed_in: TestClient, tracker: Tracker, headers: dict[str, str]
) -> None:
    """Отклоняет запись без защитного заголовка или с постороннего источника."""
    response = signed_in.post("/api/campaigns", headers=headers, json=PAYLOAD)

    assert response.status_code == 403
    assert tracker.paths == []


@pytest.mark.parametrize(
    ("step", "step_label", "expected_id"),
    [(1, "campaign", None), (2, "redirect", 42), (3, "offer_stream", 42), (4, "enable", 42)],
)
def test_rejected_step_stops_the_sequence(
    signed_in: TestClient, tracker: Tracker, step: int, step_label: str, expected_id: int | None
) -> None:
    """После отказа не повторяет запрос и сохраняет сведения о шаге."""
    tracker.fail_at = step
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == step_label
    assert detail["campaign_id"] == expected_id
    assert detail["outcome_unknown"] is False
    assert detail["refresh_options"] is (step == 1)
    assert "HTTP 406" in detail["message"]
    assert "Отклонённые поля" not in detail["message"]
    assert "diagnostic" not in detail["message"]
    assert tracker.paths == REQUESTS[:step]
    assert tracker.campaign_reads == []
    assert tracker.state == (None if step == 1 else "disabled")
    assert tracker.offer_stream_recorded == (step == 4)


@pytest.mark.parametrize(
    ("reply", "safe_labels"),
    [
        (
            {
                "group_id": ["private tracker diagnostic"],
                "traffic_source_id": ["should not appear"],
                "unknown": ["token=secret"],
                "domain_id": ["domain.example"],
            },
            "группа кампаний, источник трафика",
        ),
        (
            {"name": [], "alias": ["private", 4], "traffic_source_id": "token=secret"},
            None,
        ),
        ("token=secret", None),
    ],
)
def test_first_step_rejection_preserves_only_reported_field_labels(
    signed_in: TestClient, tracker: Tracker, reply: JsonValue, safe_labels: str | None
) -> None:
    """Отдаёт подтверждённые названия полей без чужого текста и неизвестных ключей."""
    tracker.fail_at = 1
    tracker.rejection_reply = reply
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["refresh_options"] is True
    expected_message = "Keitaro отклонил параметры кампании (HTTP 406)."
    if safe_labels:
        expected_message += f" Отклонённые поля — {safe_labels}."
    assert detail["message"] == expected_message
    assert tracker.paths == [CREATE]


def test_lost_campaign_response_requires_verification(
    signed_in: TestClient, tracker: Tracker
) -> None:
    """После потери первого ответа предупреждает о возможной записи и прекращает запросы."""
    tracker.lose_response_at = 1
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["outcome_unknown"] is True
    assert detail["refresh_options"] is False
    assert "Проверьте результат в Keitaro" in detail["message"]
    assert tracker.paths == [CREATE]
    assert tracker.state == "disabled"


def test_lost_offer_stream_response_never_enables_or_retries(
    signed_in: TestClient, tracker: Tracker
) -> None:
    """При потере ответа после записи оставляет кампанию выключенной."""
    tracker.lose_response_at = 3
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == "offer_stream"
    assert detail["campaign_id"] == 42
    assert detail["outcome_unknown"] is True
    assert "Проверьте результат в Keitaro" in detail["message"]
    assert tracker.paths == REQUESTS[:3]
    assert tracker.offer_stream_recorded
    assert tracker.state == "disabled"


def test_unconfirmed_redirect_leaves_campaign_disabled(
    signed_in: TestClient, tracker: Tracker
) -> None:
    """Не включает кампанию, если Keitaro не подтвердил адрес перенаправления."""
    tracker.omit_redirect_url = True
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == "redirect"
    assert detail["campaign_id"] == 42
    assert detail["outcome_unknown"] is True
    assert tracker.paths == REQUESTS[:2]
    assert tracker.state == "disabled"


@pytest.mark.parametrize(
    "changes",
    [
        {"campaign_id": 43},
        {"schema": "action"},
        {"state": "disabled"},
        {"type": "default"},
        {"position": 2},
        {"action_type": "status404"},
        {"action_payload": "https://example.net"},
        {"filters": []},
        {"filters": [{"name": "country", "mode": "accept", "payload": '["NZ"]'}]},
        {"filters": [{"name": "country", "mode": "reject", "payload": ["AU"]}]},
    ],
)
def test_incorrect_redirect_never_enables_campaign(
    signed_in: TestClient, tracker: Tracker, changes: dict[str, JsonValue]
) -> None:
    """Останавливает запись, если первый поток не подтверждает нужный маршрут."""
    tracker.redirect_changes = changes
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == "redirect"
    assert detail["campaign_id"] == 42
    assert detail["outcome_unknown"] is True
    assert tracker.paths == REQUESTS[:2]
    assert tracker.state == "disabled"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 88},
        {"campaign_id": 43},
        {"schema": "redirect"},
        {"state": "disabled"},
        {"type": "regular"},
        {"position": 1},
        {"landings": [{"landing_id": 99, "share": 100, "state": "active"}]},
        {"filters": [{"name": "country", "mode": "reject", "payload": ["AU"]}]},
        {"offers": []},
        {"offers": [{"offer_id": 3718, "share": 100, "state": "active"}]},
        {"offers": [{"offer_id": 3717, "share": 50, "state": "active"}]},
        {"offers": [{"offer_id": 3717, "share": 100, "state": "disabled"}]},
    ],
)
def test_incorrect_fallback_never_enables_campaign(
    signed_in: TestClient, tracker: Tracker, changes: dict[str, JsonValue]
) -> None:
    """Оставляет кампанию выключенной при неподтверждённом запасном маршруте."""
    tracker.offer_stream_changes = changes
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == "offer_stream"
    assert detail["campaign_id"] == 42
    assert detail["outcome_unknown"] is True
    assert tracker.paths == REQUESTS[:3]
    assert tracker.state == "disabled"


@pytest.mark.parametrize("state", [{}, {"state": "active"}, {"state": False}])
def test_keeps_campaign_id_when_disabled_state_is_unconfirmed(
    signed_in: TestClient, tracker: Tracker, state: dict[str, JsonValue]
) -> None:
    """Показывает известный ID, даже если выключенное состояние не подтверждено."""
    tracker.campaign_response = {"id": 42} | state
    response = signed_in.post("/api/campaigns", headers=HEADERS, json=PAYLOAD)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["step"] == "campaign"
    assert detail["campaign_id"] == 42
    assert detail["outcome_unknown"] is True
    assert tracker.paths == REQUESTS[:1]
