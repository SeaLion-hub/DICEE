"""목록 partial 인덱스에 id DESC tie-break 추가 (list_notices_paginated ORDER BY 정합).

Revision ID: 011_notices_list_id
Revises: 010_notice_taxonomy
Create Date: 2026-03-23

008에서 추가한 ix_notices_list_by_college / ix_notices_list_global 끝에 id DESC를 붙여
동일 (published_at, created_at) 구간에서 정렬·키셋 일치를 돕는다.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "011_notices_list_id"
down_revision: Union[str, Sequence[str], None] = "010_notice_taxonomy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_notices_list_by_college_new ON notices (
            college_id,
            published_at DESC NULLS LAST,
            created_at DESC,
            id DESC
        ) WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_notices_list_global_new ON notices (
            published_at DESC NULLS LAST,
            created_at DESC,
            id DESC
        ) WHERE deleted_at IS NULL
        """
    )
    op.drop_index("ix_notices_list_by_college", table_name="notices")
    op.drop_index("ix_notices_list_global", table_name="notices")
    op.execute("ALTER INDEX ix_notices_list_by_college_new RENAME TO ix_notices_list_by_college")
    op.execute("ALTER INDEX ix_notices_list_global_new RENAME TO ix_notices_list_global")


def downgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_notices_list_by_college_old ON notices (
            college_id,
            published_at DESC NULLS LAST,
            created_at DESC
        ) WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_notices_list_global_old ON notices (
            published_at DESC NULLS LAST,
            created_at DESC
        ) WHERE deleted_at IS NULL
        """
    )
    op.drop_index("ix_notices_list_by_college", table_name="notices")
    op.drop_index("ix_notices_list_global", table_name="notices")
    op.execute("ALTER INDEX ix_notices_list_by_college_old RENAME TO ix_notices_list_by_college")
    op.execute("ALTER INDEX ix_notices_list_global_old RENAME TO ix_notices_list_global")
