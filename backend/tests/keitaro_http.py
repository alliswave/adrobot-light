"""Локальный стенд Admin API для проверки приложения в браузере."""

from http import HTTPStatus
from itertools import count
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, JsonValue

type Record = dict[str, JsonValue]

OFFERS: list[dict[str, str | int]] = [
    {"id": 3717, "name": "Оффер для Австралии"},
    {"id": 3749, "name": "Оффер для Канады"},
    {"id": 11112, "name": "Оффер для Германии"},
    {"id": 12130, "name": "Оффер для Франции"},
]

groups: dict[int, Record] = {181: {"id": 181, "name": "Поиск", "type": "campaigns"}}
traffic_sources: dict[int, Record] = {
    207: {"id": 207, "name": "Поисковая реклама", "state": "active"},
    211: {"id": 211, "name": "Партнёрская сеть", "state": "active"},
}
catalog_unavailable = False
campaign_ids = count(42)
stream_ids = count(88)
campaigns: dict[int, Record] = {}
hidden_campaigns: set[int] = set()
streams: dict[int, Record] = {}
publications: list[Record] = []
campaign_writes: list[Record] = []


class CatalogName(BaseModel):
    """Название добавляемой в стенд группы."""

    name: str


class CatalogStatus(BaseModel):
    """Доступность справочников в тестовом трекере."""

    unavailable: bool


class CampaignVisibility(BaseModel):
    """Присутствие кампании в списке тестового трекера."""

    visible: bool


def require_test_key(api_key: Annotated[str, Header()]) -> None:
    """Проверяет, что приложение отправило ключ стенда в заголовке Admin API."""
    if api_key != "local-test-key":
        raise HTTPException(HTTPStatus.UNAUTHORIZED)


admin = APIRouter(prefix="/admin_api/v1", dependencies=[Depends(require_test_key)])
app = FastAPI()


@admin.get("/offers")
def list_offers() -> list[dict[str, str | int]]:
    """Возвращает каталог с идентификаторами для контрольных примеров."""
    return OFFERS


@admin.get("/groups")
def list_groups(group_type: Annotated[str, Query(alias="type")]) -> list[Record]:
    """Возвращает группы запрошенного типа."""
    return [group for group in groups.values() if group["type"] == group_type]


@admin.get("/traffic_sources")
def list_traffic_sources() -> list[Record]:
    """Возвращает источники вместе с архивными или имитирует недоступность."""
    if catalog_unavailable:
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE)
    return list(traffic_sources.values())


@admin.get("/campaigns")
def list_campaigns(offset: int, limit: int) -> list[Record]:
    """Возвращает запрошенную страницу созданных кампаний."""
    visible = [campaign for key, campaign in campaigns.items() if key not in hidden_campaigns]
    return visible[offset : offset + limit]


@admin.post("/campaigns", status_code=HTTPStatus.CREATED, response_model=None)
def create_campaign(body: Record) -> Record | JSONResponse:
    """Запоминает тело и отклоняет запрос с недоступным вариантом."""
    campaign_writes.append({"operation": "create_campaign", "body": body})
    known_group = any(str(group_id) == body.get("group_id") for group_id in groups)
    source_id = body.get("traffic_source_id")
    errors: dict[str, list[str]] = {}
    if "domain_id" in body:
        errors["domain_id"] = ["Стенд не ожидает домен."]
    if not known_group:
        errors["group_id"] = ["Группа недоступна."]
    if type(source_id) is not int or traffic_sources.get(source_id, {}).get("state") != "active":
        errors["traffic_source_id"] = ["Тестовое сообщение трекера об источнике."]
    if errors:
        return JSONResponse(errors, status_code=HTTPStatus.NOT_ACCEPTABLE)
    campaign_id = next(campaign_ids)
    campaign = {**body, "id": campaign_id}
    campaigns[campaign_id] = campaign
    return campaign


@admin.post("/campaigns/{campaign_id}/enable")
def enable_campaign(campaign_id: int) -> Record:
    """Включает кампанию и отвечает без сведений о её состоянии."""
    campaign_writes.append({"operation": "enable_campaign", "campaign_id": campaign_id})
    get_campaign(campaign_id)["state"] = "active"
    return {}


@admin.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int) -> Record:
    """Возвращает текущее состояние отдельной кампании."""
    if campaign_id not in campaigns:
        raise HTTPException(HTTPStatus.NOT_FOUND)
    return campaigns[campaign_id]


@admin.post("/streams", status_code=HTTPStatus.CREATED)
def create_stream(body: Record) -> Record:
    """Сохраняет поток и возвращает полный маршрут, включая пустые списки."""
    campaign_writes.append({"operation": "create_stream", "body": body})
    stream_id = next(stream_ids)
    stream: Record = {"filters": [], "landings": [], "offers": [], **body, "id": stream_id}
    streams[stream_id] = stream
    return stream


@admin.get("/campaigns/{campaign_id}/streams")
def campaign_streams(campaign_id: int) -> list[Record]:
    """Возвращает записанные потоки кампании в порядке их создания."""
    if campaign_id not in campaigns:
        raise HTTPException(HTTPStatus.NOT_FOUND)
    return [stream for stream in streams.values() if stream["campaign_id"] == campaign_id]


@admin.get("/streams/{stream_id}")
def get_stream(stream_id: int) -> Record:
    """Возвращает состояние отдельного потока."""
    if stream_id not in streams:
        raise HTTPException(HTTPStatus.NOT_FOUND)
    return streams[stream_id]


@admin.put("/streams/{stream_id}")
def update_stream(stream_id: int, body: Record) -> Record:
    """Запоминает исходное тело публикации и обновляет переданные поля потока."""
    stream = get_stream(stream_id)
    publications.append({"stream_id": stream_id, "body": body})
    stream.update(body)
    return stream


@app.put("/verification/groups/{group_id}")
def put_group(group_id: int, body: CatalogName) -> Record:
    """Добавляет или переименовывает группу без перезапуска стенда."""
    group: Record = {"id": group_id, "name": body.name, "type": "campaigns"}
    groups[group_id] = group
    return group


@app.delete("/verification/traffic-sources/{source_id}")
def archive_traffic_source(source_id: int) -> Record:
    """Архивирует источник, сохраняя его в выдаче тестового трекера."""
    if source_id not in traffic_sources:
        raise HTTPException(HTTPStatus.NOT_FOUND)
    source = traffic_sources[source_id]
    source["state"] = "archived"
    return source


@app.put("/verification/catalog-status", status_code=HTTPStatus.NO_CONTENT)
def set_catalog_status(status: CatalogStatus) -> None:
    """Включает или выключает ошибку чтения источников."""
    global catalog_unavailable
    catalog_unavailable = status.unavailable


@app.put("/verification/campaigns/{campaign_id}/visibility", status_code=HTTPStatus.NO_CONTENT)
def set_campaign_visibility(campaign_id: int, visibility: CampaignVisibility) -> None:
    """Меняет выдачу кампании в списке, оставляя её потоки для проверки черновика."""
    if campaign_id not in campaigns:
        raise HTTPException(HTTPStatus.NOT_FOUND)
    if visibility.visible:
        hidden_campaigns.discard(campaign_id)
    else:
        hidden_campaigns.add(campaign_id)


@app.delete("/verification/streams/{stream_id}/offers/{offer_id}")
def remove_offer(stream_id: int, offer_id: int) -> Record:
    """Удаляет привязку напрямую в стенде, сохраняя доли остальных офферов."""
    stream = get_stream(stream_id)
    bindings = stream["offers"]
    if not isinstance(bindings, list):
        raise HTTPException(HTTPStatus.NOT_FOUND)
    remaining = [
        binding
        for binding in bindings
        if not (isinstance(binding, dict) and binding["offer_id"] == offer_id)
    ]
    if len(remaining) == len(bindings):
        raise HTTPException(HTTPStatus.NOT_FOUND)
    stream["offers"] = remaining
    return stream


@app.get("/verification/state")
def tracker_state() -> dict[str, list[Record]]:
    """Показывает состояние и тела отправленных публикаций для сверки."""
    return {
        "campaigns": list(campaigns.values()),
        "streams": list(streams.values()),
        "publications": publications,
        "campaign_writes": campaign_writes,
    }


app.include_router(admin)
