"""Add login audit operational lookup index.

Revision ID: 018_login_audit_operational_index
Revises: 017_calendar_query_indexes
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018_login_audit_operational_index"
down_revision: str | Sequence[str] | None = "017_calendar_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_login_audits_ip_created
        ON login_audits (ip_hmac, created_at DESC)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_login_audits_ip_created", table_name="login_audits")
