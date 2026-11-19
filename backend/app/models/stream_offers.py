"""Таблица известных привязок офферов."""

from sqlalchemy import BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KnownStreamOffer(Base):
    """Привязка, ранее полученная от Keitaro и доступная в архиве потока."""

    __tablename__ = "known_stream_offers"

    stream_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    offer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    offer_name: Mapped[str | None] = mapped_column(Text)
