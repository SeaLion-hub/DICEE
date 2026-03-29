"""college_sources, ingestion_attempts, ingestion_batches 및 notices 전처리 컬럼.

Revision ID: 013_college_sources_ingestion
Revises: 012_notice_embedding
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "013_college_sources_ingestion"
down_revision: str | Sequence[str] | None = "012_notice_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "college_sources",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("college_id", sa.UUID(), nullable=False),
        sa.Column("list_url", sa.Text(), nullable=False),
        sa.Column("crawler_engine_key", sa.String(255), nullable=False),
        sa.Column("connector_config", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["colleges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_college_sources_college_id", "college_sources", ["college_id"])
    op.create_index(
        "uq_college_sources_one_primary",
        "college_sources",
        ["college_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = true"),
    )

    op.create_table(
        "ingestion_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("college_source_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("checkpoint_pointer", JSONB(), nullable=True),
        sa.Column("total_batches", sa.Integer(), nullable=False),
        sa.Column("completed_batches", sa.Integer(), nullable=False),
        sa.Column("total_docs", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("heartbeat_counter", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["college_source_id"], ["college_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_attempts_college_source_id", "ingestion_attempts", ["college_source_id"])
    op.create_index("ix_ingestion_attempts_status", "ingestion_attempts", ["status"])
    op.create_index("ix_ingestion_attempts_celery_task_id", "ingestion_attempts", ["celery_task_id"])

    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("drafts_payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["attempt_id"], ["ingestion_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_batches_attempt_id", "ingestion_batches", ["attempt_id"])
    op.create_index("ix_ingestion_batches_status", "ingestion_batches", ["status"])

    op.add_column("notices", sa.Column("cleaner_version", sa.String(32), nullable=True))
    op.add_column("notices", sa.Column("structured_sections", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("notices", "structured_sections")
    op.drop_column("notices", "cleaner_version")
    op.drop_index("ix_ingestion_batches_status", table_name="ingestion_batches")
    op.drop_index("ix_ingestion_batches_attempt_id", table_name="ingestion_batches")
    op.drop_table("ingestion_batches")
    op.drop_index("ix_ingestion_attempts_celery_task_id", table_name="ingestion_attempts")
    op.drop_index("ix_ingestion_attempts_status", table_name="ingestion_attempts")
    op.drop_index("ix_ingestion_attempts_college_source_id", table_name="ingestion_attempts")
    op.drop_table("ingestion_attempts")
    op.drop_index("uq_college_sources_one_primary", table_name="college_sources")
    op.drop_index("ix_college_sources_college_id", table_name="college_sources")
    op.drop_table("college_sources")
