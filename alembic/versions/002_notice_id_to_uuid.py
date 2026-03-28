"""notices.id 및 user_calendar_events.notice_id를 Integer에서 UUID v7로 전환.

Revision ID: 002_notice_uuid
Revises: v7_001
Create Date: 2026-02-24

기존 Integer PK/FK를 UUID로 변환. gen_random_uuid() 사용.
이미 notices.id가 UUID인 경우(001 적용 DB) 스킵.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_notice_uuid"
down_revision: str | Sequence[str] | None = "v7_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _notices_id_is_uuid(conn) -> bool:
    """notices.id 컬럼이 이미 UUID 타입이면 True."""
    r = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'notices' AND column_name = 'id'"
        )
    )
    row = r.fetchone()
    return row is not None and row[0] in ("uuid", "USER-DEFINED")


def upgrade() -> None:
    conn = op.get_bind()

    if _notices_id_is_uuid(conn):
        return

    # 1. notices: id_uuid 추가 및 backfill
    op.add_column(
        "notices",
        sa.Column("id_uuid", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(sa.text("UPDATE notices SET id_uuid = gen_random_uuid() WHERE id_uuid IS NULL"))

    # 2. user_calendar_events: notice_id_uuid 추가 및 backfill (기존 int notice_id → notices.id_uuid 매핑)
    op.add_column(
        "user_calendar_events",
        sa.Column("notice_id_uuid", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE user_calendar_events uce "
            "SET notice_id_uuid = n.id_uuid FROM notices n WHERE n.id = uce.notice_id"
        )
    )
    op.alter_column(
        "user_calendar_events",
        "notice_id_uuid",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    # 3. user_calendar_events FK 제거, notice_id 제거, notice_id_uuid → notice_id
    op.drop_constraint(
        "user_calendar_events_notice_id_fkey",
        "user_calendar_events",
        type_="foreignkey",
    )
    op.drop_column("user_calendar_events", "notice_id")
    op.alter_column(
        "user_calendar_events",
        "notice_id_uuid",
        new_column_name="notice_id",
    )
    op.create_foreign_key(
        "user_calendar_events_notice_id_fkey",
        "user_calendar_events",
        "notices",
        ["notice_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_user_calendar_events_notice_id",
        "user_calendar_events",
        ["notice_id"],
        unique=False,
    )

    # 4. notices PK 제거, id 제거, id_uuid → id, PK 추가
    op.drop_constraint("notices_pkey", "notices", type_="primary")
    op.drop_column("notices", "id")
    op.alter_column(
        "notices",
        "id_uuid",
        new_column_name="id",
    )
    op.alter_column(
        "notices",
        "id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_primary_key("notices_pkey", "notices", ["id"])


def downgrade() -> None:
    """UUID → Integer 변환은 데이터 손실 가능성으로 지원하지 않음."""
    raise NotImplementedError(
        "Downgrade from UUID to Integer is not supported (data loss risk)."
    )
