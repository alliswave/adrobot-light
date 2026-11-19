"""Маршруты входа, создания кампаний и редактирования потоков."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from app.adapters.keitaro import KeitaroClient, KeitaroError
from app.api.session import Operator, SessionCookie, require_operator, require_same_origin_write
from app.repositories.stream_offer_history import (
    StreamOfferHistoryError,
    StreamOfferHistoryRepository,
)
from app.repositories.users import UserRepository
from app.services.offer_shares import InvalidOfferShares, distribute_offer_shares
from app.use_cases.accounts import Credentials, authenticate
from app.use_cases.campaigns import (
    OFFER_QUERY_MAX_LENGTH,
    CampaignCreationError,
    CampaignInput,
    CampaignOptions,
    CampaignSummary,
    CreatedCampaign,
    CreationStep,
    OfferOption,
    create_campaign,
    list_campaign_options,
    list_campaigns,
    search_offers,
)
from app.use_cases.stream_editor import (
    InvalidStreamEdit,
    OfferDraft,
    PublishedHistoryError,
    StreamView,
    TrackerResourceNotFound,
    load_streams,
    publish_offers,
)

router = APIRouter(prefix="/api")

CREATION_MESSAGES = {
    CreationStep.CAMPAIGN: "Не удалось подтвердить создание выключенной кампании.",
    CreationStep.REDIRECT: "Не удалось подтвердить создание потока с перенаправлением.",
    CreationStep.OFFER_STREAM: "Не удалось подтвердить создание потока с оффером.",
    CreationStep.ENABLE: "Не удалось подтвердить включение кампании.",
}
PARAMETER_REJECTION_STATUSES = {
    HTTPStatus.BAD_REQUEST,
    HTTPStatus.NOT_ACCEPTABLE,
    HTTPStatus.UNPROCESSABLE_ENTITY,
}
CAMPAIGN_FIELD_LABELS = {
    "name": "название кампании",
    "alias": "адрес кампании",
    "group_id": "группа кампаний",
    "traffic_source_id": "источник трафика",
    "state": "состояние кампании",
    "type": "тип кампании",
}


def get_stream_offer_history(request: Request) -> StreamOfferHistoryRepository:
    """Возвращает хранилище известных привязок офферов."""
    history: StreamOfferHistoryRepository = request.app.state.stream_offer_history
    return history


def get_keitaro(request: Request) -> KeitaroClient:
    """Возвращает общий клиент Admin API."""
    keitaro: KeitaroClient = request.app.state.keitaro
    return keitaro


def get_users(request: Request) -> UserRepository:
    """Возвращает хранилище локальных учётных записей."""
    users: UserRepository = request.app.state.users
    return users


Users = Annotated[UserRepository, Depends(get_users)]
StreamOfferHistory = Annotated[StreamOfferHistoryRepository, Depends(get_stream_offer_history)]
Tracker = Annotated[KeitaroClient, Depends(get_keitaro)]
SignedIn = Annotated[Operator, Depends(require_operator)]
PositivePathId = Annotated[int, Path(gt=0)]
require_write = Depends(require_same_origin_write)


@router.get("/session")
def session_status(operator: SignedIn) -> Operator:
    """Сообщает браузеру, под какой учётной записью открыт сеанс."""
    return operator


@router.post("/session", dependencies=[require_write])
def sign_in(
    credentials: Credentials,
    request: Request,
    response: Response,
    users: Users,
    session: SessionCookie,
) -> Operator:
    """Проверяет пароль и выдаёт подписанную cookie."""
    username = authenticate(users, credentials)
    if username is None:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, "Неверный логин или пароль.")
    operator = Operator(username)
    session.write(request, response, operator)
    return operator


@router.delete("/session", status_code=HTTPStatus.NO_CONTENT, dependencies=[require_write])
def sign_out(request: Request, response: Response, session: SessionCookie) -> None:
    """Завершает текущий сеанс браузера."""
    session.clear(request, response)


@router.get("/offers")
def offers(
    operator: SignedIn,
    tracker: Tracker,
    q: Annotated[str, Query(max_length=OFFER_QUERY_MAX_LENGTH)] = "",
) -> list[OfferOption]:
    """Возвращает офферы, совпавшие с вводом оператора."""
    try:
        return search_offers(tracker, q)
    except KeitaroError as exc:
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY, "Не удалось загрузить офферы из Keitaro."
        ) from exc


@router.post(
    "/campaigns",
    status_code=HTTPStatus.CREATED,
    dependencies=[Depends(require_operator), require_write],
)
def campaigns(campaign: CampaignInput, tracker: Tracker) -> CreatedCampaign:
    """Создаёт кампанию или сообщает шаг, на котором остановилась запись."""
    try:
        return create_campaign(tracker, campaign)
    except CampaignCreationError as exc:
        message = CREATION_MESSAGES[exc.step]
        refresh_options = (
            exc.step == CreationStep.CAMPAIGN
            and not exc.cause.outcome_unknown
            and exc.cause.status in PARAMETER_REJECTION_STATUSES
        )
        if refresh_options:
            message = f"Keitaro отклонил параметры кампании (HTTP {exc.cause.status})."
            rejected_labels = [
                CAMPAIGN_FIELD_LABELS[field]
                for field in exc.cause.rejected_fields
                if field in CAMPAIGN_FIELD_LABELS
            ]
            if rejected_labels:
                message += f" Отклонённые поля — {', '.join(rejected_labels)}."
        elif exc.cause.status is not None:
            message += f" Keitaro вернул ошибку HTTP {exc.cause.status}."
        if exc.cause.outcome_unknown:
            message += " Проверьте результат в Keitaro перед повтором."
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY,
            {
                "message": message,
                "step": exc.step,
                "campaign_id": exc.campaign_id,
                "outcome_unknown": exc.cause.outcome_unknown,
                "refresh_options": refresh_options,
            },
        ) from exc


@router.get("/campaign-options", dependencies=[Depends(require_operator)])
def campaign_options(tracker: Tracker) -> CampaignOptions:
    """Возвращает группы и источники трафика для новой кампании."""
    try:
        return list_campaign_options(tracker)
    except KeitaroError as exc:
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY, "Не удалось загрузить справочники из Keitaro."
        ) from exc


@router.get("/campaigns", dependencies=[Depends(require_operator)])
def campaign_catalog(tracker: Tracker) -> list[CampaignSummary]:
    """Возвращает доступные в Keitaro кампании для выбора."""
    try:
        return list_campaigns(tracker)
    except KeitaroError as exc:
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY, "Не удалось загрузить кампании из Keitaro."
        ) from exc


@router.get("/campaigns/{campaign_id}/streams", dependencies=[Depends(require_operator)])
def campaign_streams(
    campaign_id: PositivePathId, tracker: Tracker, history: StreamOfferHistory
) -> list[StreamView]:
    """Загружает потоки и добавляет архивные офферы."""
    try:
        return load_streams(tracker, history, campaign_id)
    except TrackerResourceNotFound as exc:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(exc)) from exc
    except KeitaroError as exc:
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY, "Не удалось загрузить потоки кампании из Keitaro."
        ) from exc
    except StreamOfferHistoryError as exc:
        raise HTTPException(
            HTTPStatus.SERVICE_UNAVAILABLE, "Не удалось загрузить историю привязок офферов."
        ) from exc


@router.post("/offer-shares/preview", dependencies=[Depends(require_operator), require_write])
def preview_offer_shares(draft: OfferDraft) -> dict[int, int]:
    """Считает доли черновика без обращения к базе и Keitaro."""
    try:
        return distribute_offer_shares(draft.offer_ids, draft.pinned_shares)
    except InvalidOfferShares as exc:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.put(
    "/campaigns/{campaign_id}/streams/{stream_id}/offers",
    dependencies=[Depends(require_operator), require_write],
)
def publish_stream_offers(
    campaign_id: PositivePathId,
    stream_id: PositivePathId,
    draft: OfferDraft,
    tracker: Tracker,
    history: StreamOfferHistory,
) -> StreamView:
    """Записывает выбранный состав и сообщает, когда публикацию следует сверить."""
    try:
        return publish_offers(tracker, history, campaign_id, stream_id, draft)
    except (InvalidOfferShares, InvalidStreamEdit) as exc:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
    except TrackerResourceNotFound as exc:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(exc)) from exc
    except PublishedHistoryError as exc:
        raise HTTPException(
            HTTPStatus.SERVICE_UNAVAILABLE,
            {"message": str(exc), "outcome_unknown": False},
        ) from exc
    except KeitaroError as exc:
        if exc.outcome_unknown:
            message = "Не удалось подтвердить публикацию. Сверьте результат с Keitaro."
        elif exc.status is not None:
            message = f"Keitaro вернул ошибку HTTP {exc.status}. Черновик не опубликован."
        else:
            message = "Не удалось загрузить данные из Keitaro. Черновик не опубликован."
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY, {"message": message, "outcome_unknown": exc.outcome_unknown}
        ) from exc
