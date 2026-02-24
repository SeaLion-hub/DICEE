"""Schema contract fix: additive columns for users, notices, user_calendar_events, crawl_runs.

Revision ID: 006_schema_contract_fix
Revises: 005_login_audits
Create Date: 2026-02-24

Additive only (no drops). Aligns DB with app: profile_json, images/attachments/dates,
user_calendar_events notice_id/title/start_at/end_at, crawl_runs notices_upserted/error_message.
crawl_run_tasks remains the idempotency store; crawl_runs stores run data only (no celery_task_id).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_schema_contract_fix"
down_revision: Union[str, Sequence[str], None] = "005_login_audits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users: profile_json (5단계 매칭용)
    op.add_column("users", sa.Column("profile_json", postgresql.JSONB(), nullable=True))

    # notices: AI/원본 보존 컬럼
    op.add_column("notices", sa.Column("images", postgresql.JSONB(), nullable=True))
    op.add_column("notices", sa.Column("attachments", postgresql.JSONB(), nullable=True))
    op.add_column("notices", sa.Column("dates", postgresql.JSONB(), nullable=True))

    # user_calendar_events: code expects notice_id + title/start_at/end_at (additive; cleanup later)
    op.add_column(
        "user_calendar_events",
        sa.Column("notice_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("user_calendar_events", sa.Column("title", sa.String(512), nullable=True))
    op.add_column(
        "user_calendar_events",
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_calendar_events",
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "uq_user_calendar_user_notice",
        "user_calendar_events",
        ["user_id", "notice_id"],
        unique=True,
        postgresql_where=sa.text("notice_id IS NOT NULL"),
    )

    # crawl_runs: run metadata only (no celery_task_id; idempotency via crawl_run_tasks)
    op.add_column(
        "crawl_runs",
        sa.Column("notices_upserted", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("crawl_runs", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("crawl_runs", "error_message")
    op.drop_column("crawl_runs", "notices_upserted")

    op.drop_index("uq_user_calendar_user_notice", table_name="user_calendar_events")
    op.drop_index("ix_user_calendar_events_notice_id", table_name="user_calendar_events")
    op.drop_constraint(
        "user_calendar_events_notice_id_fkey",
        "user_calendar_events",
        type_="foreignkey",
    )
    op.drop_column("user_calendar_events", "end_at")
    op.drop_column("user_calendar_events", "start_at")
    op.drop_column("user_calendar_events", "title")
    op.drop_column("user_calendar_events", "notice_id")

    op.drop_column("notices", "dates")
    op.drop_column("notices", "attachments")
    op.drop_column("notices", "images")

    op.drop_column("users", "profile_json")
