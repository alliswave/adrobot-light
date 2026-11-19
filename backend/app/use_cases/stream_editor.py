"""Чтение фактических долей и публикация состава потока."""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, StrictInt

from app.adapters.keitaro import (
    CampaignStream,
    KeitaroClient,
    KeitaroError,
    KeitaroResourceNotFound,
    StreamKind,
    StreamOffer,
    TrackerId,
)
from app.repositories.stream_offer_history import (
    StreamOfferHistoryError,
    StreamOfferHistoryRepository,
)
from app.services.offer_shares import distribute_offer_shares

OfferState = Literal["active", "disabled", "archived"]


def _pin_offer_id(value: object) -> int:
    """Преобразует ключ JSON только из единственной десятичной записи ID."""
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and not value.startswith("0")
    ):
        return int(value)
    if type(value) is int:
        return value
    raise ValueError("Укажите ID оффера обычным целым числом без знака и начальных нулей.")


PinOfferId = Annotated[TrackerId, BeforeValidator(_pin_offer_id)]


class OfferDraft(BaseModel):
    """Упорядоченный состав черновика и закреплённые доли по ID офферов."""

    offer_ids: list[TrackerId]
    pinned_shares: dict[PinOfferId, StrictInt]


class StreamOfferView(BaseModel):
    """Название и доля привязки, показанной в редакторе."""

    id: int
    name: str
    share: int
    state: OfferState


class StreamView(BaseModel):
    """Поток с фактическими и архивными привязками."""

    id: int
    name: str
    kind: StreamKind
    offers: list[StreamOfferView]


class TrackerResourceNotFound(LookupError):
    """Кампания или поток недоступны для редактирования."""


class InvalidStreamEdit(ValueError):
    """Запрошенное изменение запрещено для текущего состояния потока."""


class PublishedHistoryError(RuntimeError):
    """Keitaro подтвердил публикацию, но локальная история не сохранена."""


def _view(stream: CampaignStream, known: Mapping[int, str | None]) -> StreamView:
    """Сначала показывает привязки Keitaro, затем отсутствующие известные офферы."""
    offers: list[StreamOfferView] = []
    if stream.kind == "offers":
        published_ids = {offer.offer_id for offer in stream.offers}
        for offer in stream.offers:
            offers.append(
                StreamOfferView(
                    id=offer.offer_id,
                    name=known.get(offer.offer_id) or f"Оффер #{offer.offer_id}",
                    share=offer.share,
                    state=offer.state,
                )
            )
        for offer_id, name in known.items():
            if offer_id not in published_ids:
                offers.append(
                    StreamOfferView(
                        id=offer_id, name=name or f"Оффер #{offer_id}", share=0, state="archived"
                    )
                )
    return StreamView(id=stream.id, name=stream.name, kind=stream.kind, offers=offers)


def load_streams(
    keitaro: KeitaroClient, history: StreamOfferHistoryRepository, campaign_id: int
) -> list[StreamView]:
    """Запоминает привязки и возвращает доли без перерасчёта."""
    try:
        streams = keitaro.list_campaign_streams(campaign_id)
    except KeitaroResourceNotFound as exc:
        raise TrackerResourceNotFound("Кампания не найдена в Keitaro.") from exc
    if any(stream.campaign_id != campaign_id for stream in streams):
        raise KeitaroError()
    editable = {stream.id: stream for stream in streams if stream.kind == "offers"}
    names = {}
    if any(stream.offers for stream in editable.values()):
        names = {offer.id: offer.name for offer in keitaro.list_offers()}

    offer_names_by_stream = {
        stream_id: {offer.offer_id: names.get(offer.offer_id) for offer in stream.offers}
        for stream_id, stream in editable.items()
    }
    known = history.record_and_list(offer_names_by_stream)
    return [_view(stream, known.get(stream.id, {})) for stream in streams]


def publish_offers(
    keitaro: KeitaroClient,
    history: StreamOfferHistoryRepository,
    campaign_id: int,
    stream_id: int,
    draft: OfferDraft,
) -> StreamView:
    """Публикует рассчитанные доли и записывает историю только после подтверждения."""
    shares = distribute_offer_shares(draft.offer_ids, draft.pinned_shares)
    not_found = "Поток не найден в выбранной кампании."
    try:
        stream = keitaro.get_stream(stream_id)
    except KeitaroResourceNotFound as exc:
        raise TrackerResourceNotFound(not_found) from exc
    if stream.id != stream_id or stream.campaign_id != campaign_id:
        raise TrackerResourceNotFound(not_found)
    if stream.kind != "offers":
        raise InvalidStreamEdit("Состав офферов у этого потока изменить нельзя.")

    disabled = [offer for offer in stream.offers if offer.state == "disabled"]
    if any(offer.offer_id in shares for offer in disabled):
        raise InvalidStreamEdit("Отключённый в Keitaro оффер нельзя добавить в действующий состав.")
    offers = [
        StreamOffer(offer_id=offer_id, share=share, state="active")
        for offer_id, share in shares.items()
    ] + disabled
    names = {offer.id: offer.name for offer in keitaro.list_offers()}
    published = keitaro.put_stream_offers(stream_id, offers)
    if (
        published.id != stream_id
        or published.campaign_id != campaign_id
        or published.kind != "offers"
        or {offer.offer_id: offer for offer in published.offers}
        != {offer.offer_id: offer for offer in offers}
    ):
        raise KeitaroError(outcome_unknown=True)

    known_ids = {offer.offer_id for offer in stream.offers + published.offers}
    try:
        known = history.record_and_list(
            {stream_id: {offer_id: names.get(offer_id) for offer_id in known_ids}}
        )
    except StreamOfferHistoryError as exc:
        raise PublishedHistoryError(
            "Keitaro принял публикацию, но сохранить историю не удалось. Загрузите поток заново."
        ) from exc
    return _view(published, known[stream_id])
