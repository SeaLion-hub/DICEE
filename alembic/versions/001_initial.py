"""initial

Revision ID: 001
Revises:
Create Date: 2026-02-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "colleges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="colleges_external_id_key"),
    )
    op.create_index("ix_colleges_external_id", "colleges", ["external_id"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_user_id", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_user_provider_uid",
        ),
    )
    op.create_index("ix_users_provider", "users", ["provider"], unique=False)
    op.create_index("ix_users_provider_user_id", "users", ["provider_user_id"], unique=False)

    op.create_table(
        "notices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("college_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("poster_image_url", sa.String(2048), nullable=True),
        sa.Column("ai_extracted_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_title", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["college_id"], ["colleges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "college_id",
            "external_id",
            name="uq_notice_college_external",
        ),
    )
    op.create_index("ix_notices_college_id", "notices", ["college_id"], unique=False)
    op.create_index("ix_notices_external_id", "notices", ["external_id"], unique=False)

    op.create_table(
        "user_calendar_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("notice_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["notice_id"], ["notices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_calendar_events_notice_id",
        "user_calendar_events",
        ["notice_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_calendar_events_user_id",
        "user_calendar_events",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_calendar_events_user_id", table_name="user_calendar_events")
    op.drop_index("ix_user_calendar_events_notice_id", table_name="user_calendar_events")
    op.drop_table("user_calendar_events")
    op.drop_index("ix_notices_external_id", table_name="notices")
    op.drop_index("ix_notices_college_id", table_name="notices")
    op.drop_table("notices")
    op.drop_index("ix_users_provider_user_id", table_name="users")
    op.drop_index("ix_users_provider", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_colleges_external_id", table_name="colleges")
    op.drop_table("colleges")
