"""add crawl_runs table for crawl success rate visibility

Revision ID: 006
Revises: 005
Create Date: 2026-02-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("college_id", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("notices_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["college_id"], ["colleges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_runs_college_id", "crawl_runs", ["college_id"], unique=False)
    op.create_index("ix_crawl_runs_celery_task_id", "crawl_runs", ["celery_task_id"], unique=False)
    op.create_index("ix_crawl_runs_started_at", "crawl_runs", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_crawl_runs_started_at", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_celery_task_id", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_college_id", table_name="crawl_runs")
    op.drop_table("crawl_runs")
