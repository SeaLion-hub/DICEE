"""add users.refresh_token_version for server-side token revoke

Revision ID: 007
Revises: 006
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, Sequence[str], None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("refresh_token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "refresh_token_version")
