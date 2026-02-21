"""add notices.ai_status for AI task 선점(FOR UPDATE SKIP LOCKED)

Revision ID: 009
Revises: 008
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, Sequence[str], None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("ai_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.create_index("ix_notices_ai_status", "notices", ["ai_status"], unique=False)
    # 기존에 이미 AI 결과가 있는 행은 done으로 설정
    op.execute(
        "UPDATE notices SET ai_status = 'done' WHERE ai_extracted_json IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_notices_ai_status", table_name="notices")
    op.drop_column("notices", "ai_status")
