"""login_audits 테이블 추가. 명세 3.2: ip_hmac·ip_hmac_key_version만 저장.

Revision ID: 005_login_audits
Revises: 004_colleges_users_uuid
Create Date: 2026-02-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_login_audits"
down_revision: str | Sequence[str] | None = "004_colleges_users_uuid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ip_hmac", sa.String(64), nullable=False),
        sa.Column("ip_hmac_key_version", sa.String(32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_audits_ip_hmac", "login_audits", ["ip_hmac"], unique=False)
    op.create_index("ix_login_audits_user_id", "login_audits", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_login_audits_user_id", table_name="login_audits")
    op.drop_index("ix_login_audits_ip_hmac", table_name="login_audits")
    op.drop_table("login_audits")
