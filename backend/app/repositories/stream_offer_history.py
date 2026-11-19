"""Хранение известных привязок, одна запись на поток и оффер."""

from collections.abc import Collection, Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import KnownStreamOffer


class StreamOfferHistoryError(RuntimeError):
    """Не удалось прочитать или обновить архив привязок."""


class StreamOfferHistoryRepository:
    """Сохраняет и читает известные привязки офферов к потокам."""

    def __init__(self, engine: Engine) -> None:
        """Принимает общий пул PostgreSQL."""
        self._engine = engine

    def record_and_list(
        self, offer_names_by_stream: Mapping[int, Mapping[int, str | None]]
    ) -> dict[int, dict[int, str | None]]:
        """Обновляет и возвращает архив указанных потоков в одной транзакции."""
        try:
            with Session(self._engine) as database, database.begin():
                for stream_id in sorted(offer_names_by_stream):
                    _remember_stream_offers(database, stream_id, offer_names_by_stream[stream_id])
                return _known_offer_names(database, offer_names_by_stream.keys())
        except SQLAlchemyError as exc:
            raise StreamOfferHistoryError from exc


def _remember_stream_offers(
    database: Session, stream_id: int, offer_names: Mapping[int, str | None]
) -> None:
    """Сохраняет увиденные привязки и обновляет только известные названия."""
    if not offer_names:
        return
    upsert = insert(KnownStreamOffer).values(
        [
            {"stream_id": stream_id, "offer_id": offer_id, "offer_name": offer_names[offer_id]}
            for offer_id in sorted(offer_names)
        ]
    )
    database.execute(
        upsert.on_conflict_do_update(
            index_elements=[KnownStreamOffer.stream_id, KnownStreamOffer.offer_id],
            set_={
                "offer_name": func.coalesce(upsert.excluded.offer_name, KnownStreamOffer.offer_name)
            },
        )
    )


def _known_offer_names(
    database: Session, stream_ids: Collection[int]
) -> dict[int, dict[int, str | None]]:
    """Возвращает сохранённые названия, сгруппированные по потоку."""
    known: dict[int, dict[int, str | None]] = {stream_id: {} for stream_id in stream_ids}
    if stream_ids:
        rows = database.scalars(
            select(KnownStreamOffer)
            .where(KnownStreamOffer.stream_id.in_(stream_ids))
            .order_by(KnownStreamOffer.offer_id)
        )
        for row in rows:
            known[row.stream_id][row.offer_id] = row.offer_name
    return known
