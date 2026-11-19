"""Создаёт архив известных привязок офферов к потокам."""

import sqlalchemy as sa
from alembic import op

revision = "0002_create_known_stream_offers"
down_revision = "0001_create_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет таблицу с уникальной парой идентификаторов потока и оффера."""
    op.create_table(
        "known_stream_offers",
        sa.Column("stream_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_name", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("stream_id", "offer_id"),
    )


def downgrade() -> None:
    """Удаляет таблицу известных привязок."""
    op.drop_table("known_stream_offers")
