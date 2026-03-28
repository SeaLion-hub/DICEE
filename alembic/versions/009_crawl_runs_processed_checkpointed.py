"""crawl_runs에 processed_count, checkpointed_at 추가 (진행률·체크포인트).

Revision ID: 009_crawl_runs
Revises: 008_notices_list
Create Date: 2026-03-01

진행률 가시성 및 향후 Resume 설계 기반. 체크포인트는 청크 upsert와 동일 트랜잭션에 갱신.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009_crawl_runs"
down_revision: str | Sequence[str] | None = "008_notices_list"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("checkpointed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "checkpointed_at")
    op.drop_column("crawl_runs", "processed_count")
