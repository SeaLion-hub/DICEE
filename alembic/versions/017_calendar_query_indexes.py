"""Add calendar range query indexes.

Revision ID: 017_calendar_query_indexes
Revises: 016_user_calendar_events_cleanup
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017_calendar_query_indexes"
down_revision: str | Sequence[str] | None = "016_user_calendar_events_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_user_calendar_events_user_start_end",
        "user_calendar_events",
        ["user_id", "start_at", "end_at"],
        unique=False,
    )
    op.create_index(
        "ix_notice_schedules_calendar_range",
        "notice_schedules",
        ["start_at", "end_at"],
        unique=False,
        postgresql_where=sa.text("is_tbd = false AND start_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notice_schedules_calendar_range", table_name="notice_schedules")
    op.drop_index("ix_user_calendar_events_user_start_end", table_name="user_calendar_events")
