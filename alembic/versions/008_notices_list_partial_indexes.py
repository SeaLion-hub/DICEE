"""목록 조회용 복합 partial 인덱스 추가 (list_notices_paginated 최적화).

Revision ID: 008_notices_list
Revises: 007_merge_heads
Create Date: 2026-03-01

WHERE deleted_at IS NULL + 정렬 컬럼(published_at DESC NULLS LAST, created_at DESC)으로
목록 쿼리가 인덱스 스캔만으로 처리되도록 함.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "008_notices_list"
down_revision: str | Sequence[str] | None = "007_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # college별 목록: deleted_at IS NULL + college_id + 정렬
    op.execute(
        """
        CREATE INDEX ix_notices_list_by_college ON notices (
            college_id,
            published_at DESC NULLS LAST,
            created_at DESC
        ) WHERE deleted_at IS NULL
        """
    )
    # 전역 목록(college_id 없을 때): deleted_at IS NULL + 정렬
    op.execute(
        """
        CREATE INDEX ix_notices_list_global ON notices (
            published_at DESC NULLS LAST,
            created_at DESC
        ) WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notices_list_global", table_name="notices")
    op.drop_index("ix_notices_list_by_college", table_name="notices")
