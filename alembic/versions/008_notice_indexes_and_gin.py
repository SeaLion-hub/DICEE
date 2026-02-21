"""add Notice B-Tree and GIN indexes for sort and JSONB filter

Revision ID: 008
Revises: 007
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "008"
down_revision: Union[str, Sequence[str], None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_notices_published_at",
        "notices",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_notices_created_at",
        "notices",
        ["created_at"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX ix_notices_hashtags_gin ON notices USING gin (hashtags)"
    )
    op.execute(
        "CREATE INDEX ix_notices_eligibility_gin ON notices USING gin (eligibility)"
    )


def downgrade() -> None:
    op.drop_index("ix_notices_eligibility_gin", table_name="notices")
    op.drop_index("ix_notices_hashtags_gin", table_name="notices")
    op.drop_index("ix_notices_created_at", table_name="notices")
    op.drop_index("ix_notices_published_at", table_name="notices")
