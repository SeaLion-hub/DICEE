"""Align user_calendar_events with the current pinned-event contract.

Revision ID: 016_user_calendar_events_cleanup
Revises: 015_ai_processing_started

The table still carried the older schedule-based v7 shape
(UUID id, notice_schedule_id, custom_title), which made current inserts fail
because notice_schedule_id remained NOT NULL. This migration converts existing
rows to the pinned-event shape and removes the legacy columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "016_user_calendar_events_cleanup"
down_revision: str | Sequence[str] | None = "015_ai_processing_started"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    columns = {col["name"]: col for col in insp.get_columns("user_calendar_events")}
    indexes = {idx["name"] for idx in insp.get_indexes("user_calendar_events")}
    fks = {fk["name"] for fk in insp.get_foreign_keys("user_calendar_events")}
    pk_name = insp.get_pk_constraint("user_calendar_events").get("name")

    if "notice_schedule_id" in columns:
        op.execute(
            sa.text(
                """
                UPDATE user_calendar_events AS uce
                SET
                    notice_id = COALESCE(uce.notice_id, ns.notice_id),
                    title = COALESCE(uce.title, uce.custom_title, n.title),
                    start_at = COALESCE(uce.start_at, ns.start_at, uce.created_at),
                    end_at = COALESCE(uce.end_at, ns.end_at)
                FROM notice_schedules AS ns
                JOIN notices AS n ON n.id = ns.notice_id
                WHERE uce.notice_schedule_id = ns.id
                """
            )
        )

    op.execute(
        sa.text(
            """
            DELETE FROM user_calendar_events
            WHERE notice_id IS NULL OR title IS NULL OR start_at IS NULL
            """
        )
    )

    if "id" in columns and isinstance(columns["id"]["type"], postgresql.UUID):
        op.execute("ALTER TABLE user_calendar_events ADD COLUMN id_new SERIAL")
        if pk_name:
            op.drop_constraint(pk_name, "user_calendar_events", type_="primary")
        op.drop_column("user_calendar_events", "id")
        op.alter_column("user_calendar_events", "id_new", new_column_name="id")
        op.create_primary_key("user_calendar_events_pkey", "user_calendar_events", ["id"])

    if "uq_user_calendar_user_schedule" in indexes:
        op.drop_index("uq_user_calendar_user_schedule", table_name="user_calendar_events")
    if "ix_user_calendar_events_notice_schedule_id" in indexes:
        op.drop_index("ix_user_calendar_events_notice_schedule_id", table_name="user_calendar_events")
    if "user_calendar_events_notice_schedule_id_fkey" in fks:
        op.drop_constraint(
            "user_calendar_events_notice_schedule_id_fkey",
            "user_calendar_events",
            type_="foreignkey",
        )

    if "custom_title" in columns:
        op.drop_column("user_calendar_events", "custom_title")
    if "notice_schedule_id" in columns:
        op.drop_column("user_calendar_events", "notice_schedule_id")

    op.alter_column(
        "user_calendar_events",
        "notice_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "user_calendar_events",
        "title",
        existing_type=sa.String(length=512),
        nullable=False,
    )
    op.alter_column(
        "user_calendar_events",
        "start_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    if "uq_user_calendar_user_notice" not in indexes:
        op.create_index(
            "uq_user_calendar_user_notice",
            "user_calendar_events",
            ["user_id", "notice_id"],
            unique=True,
        )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for user_calendar_events cleanup.")
