"""notices.ai_processing_started_at: AI 선점 시각(스테일 processing 복구용).

Revision ID: 015_ai_processing_started
Revises: 014_ingestion_one_running
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_ai_processing_started"
down_revision: str | Sequence[str] | None = "014_ingestion_one_running"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("ai_processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notices_ai_status_processing_started",
        "notices",
        ["ai_status", "ai_processing_started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notices_ai_status_processing_started", table_name="notices")
    op.drop_column("notices", "ai_processing_started_at")
