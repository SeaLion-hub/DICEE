"""ingestion_attempts: college_source당 동시 RUNNING 1건 부분 유니크 인덱스.

Revision ID: 014_ingestion_one_running
Revises: 013_college_sources_ingestion
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_ingestion_one_running"
down_revision: str | Sequence[str] | None = "013_college_sources_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_ingestion_attempts_one_running_per_source",
        "ingestion_attempts",
        ["college_source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running' AND finished_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ingestion_attempts_one_running_per_source",
        table_name="ingestion_attempts",
    )
