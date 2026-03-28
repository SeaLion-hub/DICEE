"""notice_contents 테이블 추가, notices.raw_html 제거.

Revision ID: 003_notice_contents
Revises: 002_notice_uuid
Create Date: 2026-02-24

명세: 본문은 S3 등에 저장, DB에는 content_url만 notice_contents에 보관.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_notice_contents"
down_revision: str | Sequence[str] | None = "002_notice_uuid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(conn, table: str, column: str) -> bool:
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return r.fetchone() is not None


def _table_exists(conn, table: str) -> bool:
    r = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "notice_contents"):
        op.create_table(
            "notice_contents",
            sa.Column("notice_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("content_url", sa.String(2048), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["notice_id"], ["notices.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("notice_id"),
        )
    if _has_column(conn, "notices", "raw_html"):
        op.drop_column("notices", "raw_html")


def downgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("raw_html", sa.Text(), nullable=True),
    )
    op.drop_table("notice_contents")
