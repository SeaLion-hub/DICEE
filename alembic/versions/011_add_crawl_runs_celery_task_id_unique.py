"""add unique on crawl_runs.celery_task_id for upsert (retry 시 상태 단일화)

Revision ID: 011
Revises: 010
Create Date: 2026-02-22

celery_task_id 중복 시 1건만 유지. INSERT ON CONFLICT DO UPDATE로 upsert.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, Sequence[str], None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # celery_task_id가 NOT NULL인 행만 유니크. NULL은 여러 개 허용.
    op.create_index(
        "uq_crawl_runs_celery_task_id",
        "crawl_runs",
        ["celery_task_id"],
        unique=True,
        postgresql_where=sa.text("celery_task_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_crawl_runs_celery_task_id", table_name="crawl_runs")
