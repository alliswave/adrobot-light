"""Вызовы Admin API и проверка ответов Keitaro."""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Annotated, Literal, Self

import httpx
from pydantic import (
    BaseModel,
    Field,
    Json,
    JsonValue,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.settings import Settings

TrackerId = Annotated[int, Field(gt=0, strict=True)]
CAMPAIGN_PAGE_SIZE = 100
CAMPAIGN_GROUP_TYPE = "campaigns"
StreamKind = Literal["offers", "redirect", "other"]


class TrackerEntity(BaseModel):
    """Сущность с подтверждённым идентификатором Keitaro."""

    id: TrackerId


class Offer(TrackerEntity):
    """Оффер, доступный в каталоге Keitaro."""

    name: str
    state: str = "active"


class CampaignConfirmation(TrackerEntity):
    """Подтверждение состояния кампании."""

    state: JsonValue = None

    @property
    def is_disabled(self) -> bool:
        """Проверяет, что новая кампания создана выключенной."""
        return self.state == "disabled"


class TrackerCampaign(TrackerEntity):
    """Кампания, доступная в каталоге Keitaro."""

    name: str


class CampaignGroup(TrackerEntity):
    """Группа из каталога Keitaro с типом для проверки выдачи."""

    name: str
    type: str = CAMPAIGN_GROUP_TYPE


class TrafficSource(TrackerEntity):
    """Источник трафика из каталога Keitaro с текущим состоянием."""

    name: str
    state: str | None = None


class StreamFilter(BaseModel):
    """Условие потока с исходным массивом значений или его записью в JSON."""

    name: str
    mode: str
    payload: list[str] | Json[list[str]]


class StreamRoute(BaseModel):
    """Настройки потока, от которых зависит выбор маршрута."""

    campaign_id: TrackerId
    flow_schema: str = Field(alias="schema")
    type: str
    position: int
    state: str
    filters: list[StreamFilter]


class RedirectRoute(StreamRoute):
    """Маршрут потока с перенаправлением."""

    action_payload: str
    action_type: str


class RedirectConfirmation(RedirectRoute):
    """Подтверждённый маршрут с идентификатором потока."""

    id: TrackerId


class StreamOffer(BaseModel):
    """Подтверждённая привязка оффера с состоянием и долей трафика."""

    offer_id: TrackerId
    share: int
    state: Literal["active", "disabled"]


class OfferStreamRoute(StreamRoute):
    """Привязки офферов и посадочные страницы запасного потока."""

    offers: list[StreamOffer]
    landings: list[JsonValue]


class OfferStreamConfirmation(OfferStreamRoute):
    """Подтверждённый запасной маршрут с идентификатором потока."""

    id: TrackerId


class CampaignStream(TrackerEntity):
    """Поток с принадлежностью, схемой и фактическими привязками."""

    campaign_id: TrackerId
    name: str
    schema_name: str = Field(alias="schema")
    offers: list[StreamOffer] = Field(default_factory=list)

    @property
    def kind(self) -> StreamKind:
        """Сопоставляет схему Keitaro с доступными в приложении видами потоков."""
        if self.schema_name == "landings":
            return "offers"
        if self.schema_name == "redirect":
            return "redirect"
        return "other"

    @model_validator(mode="after")
    def verify_offer_bindings(self) -> Self:
        """Требует полный список привязок с уникальными ID у потока с офферами."""
        if self.schema_name == "landings" and "offers" not in self.model_fields_set:
            raise ValueError("Keitaro не вернул привязки офферов.")
        if len({offer.offer_id for offer in self.offers}) != len(self.offers):
            raise ValueError("Keitaro вернул повторяющиеся привязки офферов.")
        return self


class KeitaroError(Exception):
    """Ответ API или сбой связи с указанием определённости результата записи."""

    def __init__(
        self,
        status: int | None = None,
        *,
        outcome_unknown: bool = False,
        rejected_fields: tuple[str, ...] = (),
    ) -> None:
        """Сохраняет статус и имена отклонённых полей из исходящего запроса."""
        super().__init__("Сбой запроса к Keitaro.")
        self.status = status
        self.outcome_unknown = outcome_unknown
        self.rejected_fields = rejected_fields


class KeitaroResourceNotFound(KeitaroError):
    """Keitaro сообщил, что запрошенный объект не найден."""


def _rejected_request_fields(
    response: httpx.Response, body: Mapping[str, JsonValue] | None
) -> tuple[str, ...]:
    """Распознаёт поля в документированном ответе 406, отбрасывая тексты ошибок."""
    if response.status_code != HTTPStatus.NOT_ACCEPTABLE or body is None:
        return ()
    try:
        errors: object = response.json()
    except ValueError:
        return ()
    if not isinstance(errors, dict):
        return ()
    rejected = []
    for field_name in body:
        messages = errors.get(field_name)
        if (
            isinstance(messages, list)
            and messages
            and all(isinstance(msg, str) for msg in messages)
        ):
            rejected.append(field_name)
    return tuple(rejected)


class KeitaroClient:
    """Изолирует HTTP и форматы чтения и записи Keitaro."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        """Использует HTTP-клиент со сроком жизни приложения."""
        self._http = http
        self._headers = {"Api-Key": settings.keitaro_api_key.get_secret_value()}

    def _request_json[T](
        self,
        method: str,
        path: str,
        response_type: TypeAdapter[T],
        *,
        body: Mapping[str, JsonValue] | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> T:
        """Выполняет один запрос, проверяет ответ и не повторяет запись."""
        write = method != "GET"
        try:
            response = self._http.request(
                method, path, json=body, params=params, headers=self._headers
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == HTTPStatus.NOT_FOUND:
                raise KeitaroResourceNotFound(status) from exc
            raise KeitaroError(
                status,
                outcome_unknown=write and status >= HTTPStatus.INTERNAL_SERVER_ERROR,
                rejected_fields=_rejected_request_fields(exc.response, body),
            ) from exc
        except httpx.RequestError as exc:
            raise KeitaroError(outcome_unknown=write) from exc

        try:
            return response_type.validate_json(response.content)
        except ValidationError as exc:
            raise KeitaroError(outcome_unknown=write) from exc

    def list_offers(self) -> list[Offer]:
        """Загружает каталог офферов из трекера."""
        return self._request_json("GET", "offers", _offers)

    def list_campaign_groups(self) -> list[CampaignGroup]:
        """Читает группы из каталога кампаний."""
        groups = self._request_json("GET", "groups", _groups, params={"type": CAMPAIGN_GROUP_TYPE})
        return [group for group in groups if group.type == CAMPAIGN_GROUP_TYPE]

    def list_traffic_sources(self) -> list[TrafficSource]:
        """Читает каталог источников трафика из трекера."""
        return self._request_json("GET", "traffic_sources", _traffic_sources)

    def create_disabled_campaign(
        self, name: str, alias: str, *, group_id: int, traffic_source_id: int
    ) -> CampaignConfirmation:
        """Создаёт выключенную кампанию и читает подтверждённое состояние."""
        return self._request_json(
            "POST",
            "campaigns",
            _campaign,
            body={
                "name": name,
                "alias": alias,
                "state": "disabled",
                "type": "position",
                "group_id": str(group_id),
                "traffic_source_id": traffic_source_id,
            },
        )

    def create_country_redirect(self, campaign_id: int, country: str, name: str, url: str) -> int:
        """Создаёт поток для страны и сверяет схему перенаправления."""
        route = RedirectRoute(
            campaign_id=campaign_id,
            state="active",
            type="regular",
            position=1,
            schema="redirect",
            action_type="http",
            action_payload=url,
            filters=[StreamFilter(name="country", mode="accept", payload=[country])],
        )
        route_fields = route.model_dump(mode="json", by_alias=True)
        confirmed = self._request_json(
            "POST", "streams", _redirect, body={"name": name, **route_fields}
        )
        if confirmed.model_dump(mode="json", by_alias=True, exclude={"id"}) != route_fields:
            raise KeitaroError(outcome_unknown=True)
        return confirmed.id

    def create_fallback_offer_stream(self, campaign_id: int, offer_id: int, share: int) -> int:
        """Создаёт запасной поток и сверяет его привязку к офферу."""
        route = OfferStreamRoute(
            campaign_id=campaign_id,
            state="active",
            type="default",
            position=2,
            schema="landings",
            landings=[],
            filters=[],
            offers=[StreamOffer(offer_id=offer_id, share=share, state="active")],
        )
        confirmed = self._request_json(
            "POST",
            "streams",
            _offer_stream,
            body={
                "name": "Остальные страны",
                "action_type": "http",
                **route.model_dump(mode="json", by_alias=True, exclude={"filters", "landings"}),
            },
        )
        if confirmed.model_dump(exclude={"id"}) != route.model_dump():
            raise KeitaroError(outcome_unknown=True)
        return confirmed.id

    def enable_campaign(self, campaign_id: int) -> None:
        """Включает кампанию и при неполном подтверждении один раз читает её состояние."""
        path = f"campaigns/{campaign_id}"
        try:
            enabled = self._request_json("POST", f"{path}/enable", _campaign)
        except KeitaroError as exc:
            if not exc.outcome_unknown:
                raise
            enable_error = exc
        else:
            if enabled.id == campaign_id and enabled.state == "active":
                return
            enable_error = KeitaroError(outcome_unknown=True)

        try:
            confirmed = self._request_json("GET", path, _campaign)
        except KeitaroError as exc:
            raise enable_error from exc
        if confirmed.id != campaign_id or confirmed.state != "active":
            raise enable_error

    def list_campaigns(self) -> list[TrackerCampaign]:
        """Читает каталог до пустой страницы, даже если сервер уменьшил размер выдачи."""
        campaigns: dict[int, TrackerCampaign] = {}
        offset = 0
        while page := self._request_json(
            "GET", "campaigns", _campaigns, params={"offset": offset, "limit": CAMPAIGN_PAGE_SIZE}
        ):
            previous_count = len(campaigns)
            campaigns.update((item.id, item) for item in page)
            if len(campaigns) == previous_count:
                raise KeitaroError()
            offset += len(page)
        return list(campaigns.values())

    def list_campaign_streams(self, campaign_id: int) -> list[CampaignStream]:
        """Читает потоки, относящиеся к выбранной кампании."""
        return self._request_json("GET", f"campaigns/{campaign_id}/streams", _campaign_streams)

    def get_stream(self, stream_id: int) -> CampaignStream:
        """Читает актуальные привязки потока перед обновлением."""
        return self._request_json("GET", f"streams/{stream_id}", _campaign_stream)

    def put_stream_offers(self, stream_id: int, offers: list[StreamOffer]) -> CampaignStream:
        """Передаёт только привязки: Admin API обновляет переданные поля потока."""
        bindings: list[JsonValue] = [offer.model_dump(mode="json") for offer in offers]
        return self._request_json(
            "PUT", f"streams/{stream_id}", _campaign_stream, body={"offers": bindings}
        )


_offers = TypeAdapter(list[Offer])
_groups = TypeAdapter(list[CampaignGroup])
_traffic_sources = TypeAdapter(list[TrafficSource])
_campaign = TypeAdapter(CampaignConfirmation)
_redirect = TypeAdapter(RedirectConfirmation)
_offer_stream = TypeAdapter(OfferStreamConfirmation)
_campaigns = TypeAdapter(list[TrackerCampaign])
_campaign_streams = TypeAdapter(list[CampaignStream])
_campaign_stream = TypeAdapter(CampaignStream)
