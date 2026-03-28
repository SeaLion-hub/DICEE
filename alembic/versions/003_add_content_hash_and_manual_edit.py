"""add content_hash and is_manual_edited to notices

Revision ID: 003
Revises: 002
Create Date: 2026-02-17

content_hash: 제목+본문 해시. 3·4단계 변경 감지용.
is_manual_edited: 관리자 수동 수정 여부. AI 재덮어쓰기 방지.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.legacy_alembic_guard import v7_base_schema_present

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if v7_base_schema_present(op.get_bind()):
        return
    op.add_column(
        "notices",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_notices_content_hash", "notices", ["content_hash"], unique=False)
    op.add_column(
        "notices",
        sa.Column("is_manual_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("notices", "is_manual_edited")
    op.drop_index("ix_notices_content_hash", table_name="notices")
    op.drop_column("notices", "content_hash")
