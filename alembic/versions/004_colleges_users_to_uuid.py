"""colleges.id, users.id 및 관련 FK를 Integer에서 UUID v7로 전환.

Revision ID: 004_colleges_users_uuid
Revises: 003_notice_contents
Create Date: 2026-02-24

pg_uuidv7 확장 사용. 이미 UUID인 경우 스킵.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_colleges_users_uuid"
down_revision: Union[str, Sequence[str], None] = "003_notice_contents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_type(conn, table: str, column: str) -> str | None:
    r = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    row = r.fetchone()
    return row[0] if row else None


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "pg_uuidv7";'))

    # 1. colleges.id -> UUID (id_uuid 추가, 자식 백필, 자식 FK/컬럼 전환, colleges PK 전환, FK 재생성)
    if _col_type(conn, "colleges", "id") not in ("uuid", "USER-DEFINED"):
        op.add_column("colleges", sa.Column("id_uuid", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(sa.text("UPDATE colleges SET id_uuid = uuid_generate_v7() WHERE id_uuid IS NULL"))
        op.add_column("notices", sa.Column("college_id_uuid", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(
            sa.text("UPDATE notices n SET college_id_uuid = c.id_uuid FROM colleges c WHERE c.id = n.college_id")
        )
        op.drop_constraint("notices_college_id_fkey", "notices", type_="foreignkey")
        op.drop_column("notices", "college_id")
        op.alter_column("notices", "college_id_uuid", new_column_name="college_id")
        op.alter_column("notices", "college_id", nullable=False)
        op.add_column("crawl_runs", sa.Column("college_id_uuid", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(
            sa.text("UPDATE crawl_runs cr SET college_id_uuid = c.id_uuid FROM colleges c WHERE c.id = cr.college_id")
        )
        op.drop_constraint("crawl_runs_college_id_fkey", "crawl_runs", type_="foreignkey")
        op.drop_column("crawl_runs", "college_id")
        op.alter_column("crawl_runs", "college_id_uuid", new_column_name="college_id")
        op.alter_column("crawl_runs", "college_id", nullable=False)
        op.drop_constraint("colleges_pkey", "colleges", type_="primary")
        op.drop_column("colleges", "id")
        op.alter_column("colleges", "id_uuid", new_column_name="id")
        op.alter_column("colleges", "id", nullable=False)
        op.create_primary_key("colleges_pkey", "colleges", ["id"])
        op.create_foreign_key("notices_college_id_fkey", "notices", "colleges", ["college_id"], ["id"], ondelete="CASCADE")
        op.create_index("ix_notices_college_id", "notices", ["college_id"], unique=False)
        op.create_foreign_key("crawl_runs_college_id_fkey", "crawl_runs", "colleges", ["college_id"], ["id"], ondelete="CASCADE")
        op.create_index("ix_crawl_runs_college_id", "crawl_runs", ["college_id"], unique=False)

    # 2. users.id -> UUID
    if _col_type(conn, "users", "id") not in ("uuid", "USER-DEFINED"):
        op.add_column("users", sa.Column("id_uuid", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(sa.text("UPDATE users SET id_uuid = uuid_generate_v7() WHERE id_uuid IS NULL"))
        op.add_column("user_calendar_events", sa.Column("user_id_uuid", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(
            sa.text("UPDATE user_calendar_events uce SET user_id_uuid = u.id_uuid FROM users u WHERE u.id = uce.user_id")
        )
        op.drop_constraint("user_calendar_events_user_id_fkey", "user_calendar_events", type_="foreignkey")
        op.drop_column("user_calendar_events", "user_id")
        op.alter_column("user_calendar_events", "user_id_uuid", new_column_name="user_id")
        op.alter_column("user_calendar_events", "user_id", nullable=False)
        op.create_foreign_key("user_calendar_events_user_id_fkey", "user_calendar_events", "users", ["user_id"], ["id"], ondelete="CASCADE")
        op.create_index("ix_user_calendar_events_user_id", "user_calendar_events", ["user_id"], unique=False)
        op.drop_constraint("users_pkey", "users", type_="primary")
        op.drop_column("users", "id")
        op.alter_column("users", "id_uuid", new_column_name="id")
        op.alter_column("users", "id", nullable=False)
        op.create_primary_key("users_pkey", "users", ["id"])


def downgrade() -> None:
    raise NotImplementedError("UUID to Integer downgrade not supported (data loss risk).")
