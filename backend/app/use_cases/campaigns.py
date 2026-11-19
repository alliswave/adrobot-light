"""Поиск офферов и последовательное создание кампании с двумя потоками."""

import re
import unicodedata
from enum import StrEnum
from typing import Annotated
from uuid import uuid4

import pycountry
from pydantic import BaseModel, StringConstraints, field_validator

from app.adapters.keitaro import KeitaroClient, KeitaroError, TrackerId
from app.services.offer_shares import FULL_OFFER_SHARE

GOOGLE_URL = "https://google.com"
ALIAS_STEM_LENGTH = 60
ALIAS_SUFFIX_LENGTH = 12
OFFER_QUERY_MAX_LENGTH = 200
ACTIVE_SOURCE_STATE = "active"


class OfferOption(BaseModel):
    """Краткое представление оффера для выбора в форме."""

    id: int
    name: str


class CampaignInput(BaseModel):
    """Проверенные данные формы создания кампании."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    country: Annotated[
        str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$")
    ]
    offer_id: TrackerId
    group_id: TrackerId
    traffic_source_id: TrackerId

    @field_validator("country")
    @classmethod
    def country_exists(cls, country: str) -> str:
        """Допускает только страны из справочника ISO 3166-1."""
        if pycountry.countries.get(alpha_2=country) is None:
            raise ValueError("Укажите код страны ISO 3166-1.")
        return country


class CreatedCampaign(BaseModel):
    """Результат создания кампании."""

    id: int
    name: str


class CampaignSummary(BaseModel):
    """Кампания, доступная в каталоге Keitaro."""

    id: TrackerId
    name: str


class CampaignOption(BaseModel):
    """Идентификатор и название варианта выбора для новой кампании."""

    id: TrackerId
    name: str


class CampaignOptions(BaseModel):
    """Доступные группы и источники для формы создания кампании."""

    groups: list[CampaignOption]
    traffic_sources: list[CampaignOption]


class CreationStep(StrEnum):
    """Шаги операции, которые можно указать в сообщении об ошибке."""

    CAMPAIGN = "campaign"
    REDIRECT = "redirect"
    OFFER_STREAM = "offer_stream"
    ENABLE = "enable"


class CampaignCreationError(Exception):
    """Сбой создания с указанием шага и уже известного ID кампании."""

    def __init__(self, step: CreationStep, campaign_id: int | None, cause: KeitaroError) -> None:
        """Запоминает сведения, которые понадобятся для проверки в трекере."""
        super().__init__(step)
        self.step = step
        self.campaign_id = campaign_id
        self.cause = cause


def search_offers(keitaro: KeitaroClient, query: str) -> list[OfferOption]:
    """Ищет доступные офферы по части названия или идентификатора."""
    query = query.strip().casefold()
    return [
        OfferOption(id=offer.id, name=offer.name)
        for offer in keitaro.list_offers()
        if offer.state != "deleted" and (query in offer.name.casefold() or query in str(offer.id))
    ]


def list_campaign_options(keitaro: KeitaroClient) -> CampaignOptions:
    """Загружает свежие справочники и оставляет только доступные варианты."""
    groups = [
        CampaignOption(id=group.id, name=group.name) for group in keitaro.list_campaign_groups()
    ]
    traffic_sources = [
        CampaignOption(id=source.id, name=source.name)
        for source in keitaro.list_traffic_sources()
        if source.state == ACTIVE_SOURCE_STATE
    ]
    return CampaignOptions(groups=groups, traffic_sources=traffic_sources)


def list_campaigns(keitaro: KeitaroClient) -> list[CampaignSummary]:
    """Возвращает идентификаторы и названия кампаний для выбора в редакторе."""
    return [
        CampaignSummary(id=campaign.id, name=campaign.name) for campaign in keitaro.list_campaigns()
    ]


def campaign_alias(name: str) -> str:
    """Готовит безопасный сегмент URL с коротким случайным суффиксом."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:ALIAS_STEM_LENGTH].rstrip("-")
    return f"{stem or 'campaign'}-{uuid4().hex[:ALIAS_SUFFIX_LENGTH]}"


def create_campaign(keitaro: KeitaroClient, campaign: CampaignInput) -> CreatedCampaign:
    """Создаёт выключенную кампанию, настраивает потоки и включает её."""
    step = CreationStep.CAMPAIGN
    campaign_id: int | None = None
    try:
        created = keitaro.create_disabled_campaign(
            campaign.name,
            campaign_alias(campaign.name),
            group_id=campaign.group_id,
            traffic_source_id=campaign.traffic_source_id,
        )
        campaign_id = created.id
        if not created.is_disabled:
            raise KeitaroError(outcome_unknown=True)

        step = CreationStep.REDIRECT
        redirect_id = keitaro.create_country_redirect(
            campaign_id, campaign.country, name=f"{campaign.country} → Google", url=GOOGLE_URL
        )

        step = CreationStep.OFFER_STREAM
        offer_stream_id = keitaro.create_fallback_offer_stream(
            campaign_id, campaign.offer_id, FULL_OFFER_SHARE
        )
        if offer_stream_id == redirect_id:
            raise KeitaroError(outcome_unknown=True)

        step = CreationStep.ENABLE
        keitaro.enable_campaign(campaign_id)
    except KeitaroError as exc:
        raise CampaignCreationError(step, campaign_id, exc) from exc
    return CreatedCampaign(id=campaign_id, name=campaign.name)
