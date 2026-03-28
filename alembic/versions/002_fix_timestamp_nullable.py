"""fix timestamp nullable

Revision ID: 002
Revises: 001
Create Date: 2026-02-17

ORM과 마이그레이션 nullable 불일치 수정.
created_at, updated_at를 nullable=False로 변경 (ORM Mapped[datetime]과 일치).

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.legacy_alembic_guard import v7_base_schema_present

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# for alter_column existing_type
dt_tz = sa.DateTime(timezone=True)


def upgrade() -> None:
    if v7_base_schema_present(op.get_bind()):
        return
    # users
    op.alter_column(
        "users",
        "created_at",
        existing_type=dt_tz,
        nullable=False,
    )
    op.alter_column(
        "users",
        "updated_at",
        existing_type=dt_tz,
        nullable=False,
    )
    # notices
    op.alter_column(
        "notices",
        "created_at",
        existing_type=dt_tz,
        nullable=False,
    )
    op.alter_column(
        "notices",
        "updated_at",
        existing_type=dt_tz,
        nullable=False,
    )
    # user_calendar_events
    op.alter_column(
        "user_calendar_events",
        "created_at",
        existing_type=dt_tz,
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_calendar_events",
        "created_at",
        existing_type=dt_tz,
        nullable=True,
    )
    op.alter_column(
        "notices",
        "updated_at",
        existing_type=dt_tz,
        nullable=True,
    )
    op.alter_column(
        "notices",
        "created_at",
        existing_type=dt_tz,
        nullable=True,
    )
    op.alter_column(
        "users",
        "updated_at",
        existing_type=dt_tz,
        nullable=True,
    )
    op.alter_column(
        "users",
        "created_at",
        existing_type=dt_tz,
        nullable=True,
    )
