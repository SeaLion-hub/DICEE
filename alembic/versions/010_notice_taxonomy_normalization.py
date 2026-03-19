"""Normalize notice taxonomy persistence into child table.

Revision ID: 010_notice_taxonomy
Revises: 009_crawl_runs
Create Date: 2026-03-19

Creates notice_taxonomy_mappings and drops notices.category/sub_category.
Backfills rows from ai_extracted_json.taxonomy_mappings and legacy columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_notice_taxonomy"
down_revision: Union[str, Sequence[str], None] = "009_crawl_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notice_taxonomy_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("notice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("main_category", sa.String(length=64), nullable=False),
        sa.Column("sub_category", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["notice_id"], ["notices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notice_id",
            "main_category",
            "sub_category",
            name="uq_notice_taxonomy_mappings_triplet",
        ),
    )
    op.create_index(
        "ix_notice_taxonomy_mappings_notice_id",
        "notice_taxonomy_mappings",
        ["notice_id"],
        unique=False,
    )
    op.create_index(
        "ix_notice_taxonomy_main_notice",
        "notice_taxonomy_mappings",
        ["main_category", "notice_id"],
        unique=False,
    )
    op.create_index(
        "ix_notice_taxonomy_main_sub_notice",
        "notice_taxonomy_mappings",
        ["main_category", "sub_category", "notice_id"],
        unique=False,
    )

    # Backfill from structured extraction json taxonomy_mappings.
    op.execute(
        sa.text(
            """
            INSERT INTO notice_taxonomy_mappings (notice_id, main_category, sub_category)
            SELECT
                n.id AS notice_id,
                tm.elem ->> 'main_category' AS main_category,
                sc.value AS sub_category
            FROM notices AS n
            CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(n.ai_extracted_json -> 'taxonomy_mappings', '[]'::jsonb)
            ) AS tm(elem)
            CROSS JOIN LATERAL jsonb_array_elements_text(
                COALESCE(tm.elem -> 'sub_categories', '[]'::jsonb)
            ) AS sc(value)
            WHERE
                COALESCE(tm.elem ->> 'main_category', '') <> ''
                AND COALESCE(sc.value, '') <> ''
            ON CONFLICT (notice_id, main_category, sub_category) DO NOTHING
            """
        )
    )

    # Legacy fallback backfill: category/sub_category 값이 있으면 1행으로 보존.
    op.execute(
        sa.text(
            """
            INSERT INTO notice_taxonomy_mappings (notice_id, main_category, sub_category)
            SELECT
                n.id,
                n.category,
                n.sub_category
            FROM notices AS n
            WHERE n.category IS NOT NULL
              AND n.sub_category IS NOT NULL
            ON CONFLICT (notice_id, main_category, sub_category) DO NOTHING
            """
        )
    )

    op.execute(sa.text("DROP INDEX IF EXISTS ix_notices_category"))
    op.drop_column("notices", "sub_category")
    op.drop_column("notices", "category")


def downgrade() -> None:
    op.add_column("notices", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column("notices", sa.Column("sub_category", sa.String(length=64), nullable=True))
    op.create_index("ix_notices_category", "notices", ["category"], unique=False)

    # Downgrade 시 대표값 1건만 notices.category/sub_category로 복원.
    op.execute(
        sa.text(
            """
            UPDATE notices AS n
            SET
                category = src.main_category,
                sub_category = src.sub_category
            FROM (
                SELECT DISTINCT ON (notice_id)
                    notice_id,
                    main_category,
                    sub_category
                FROM notice_taxonomy_mappings
                ORDER BY notice_id, created_at ASC, id ASC
            ) AS src
            WHERE n.id = src.notice_id
            """
        )
    )

    op.drop_index("ix_notice_taxonomy_main_sub_notice", table_name="notice_taxonomy_mappings")
    op.drop_index("ix_notice_taxonomy_main_notice", table_name="notice_taxonomy_mappings")
    op.drop_index("ix_notice_taxonomy_mappings_notice_id", table_name="notice_taxonomy_mappings")
    op.drop_table("notice_taxonomy_mappings")

