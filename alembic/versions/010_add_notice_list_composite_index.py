"""add Notice list API composite index (college_id, published_at DESC, id DESC)

Revision ID: 010
Revises: 009
Create Date: 2026-02-22

공지 목록 API(college_id + published_at/id 정렬) 프로덕션 수준 최적화.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "010"
down_revision: Union[str, Sequence[str], None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_notices_college_published_id "
        "ON notices (college_id, published_at DESC NULLS LAST, id DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_notices_college_published_id", table_name="notices")
