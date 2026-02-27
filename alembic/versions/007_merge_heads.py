"""Merge multiple heads so 'alembic upgrade head' is unambiguous.

Revision ID: 007_merge_heads
Revises: 006, 006_schema_contract_fix
Create Date: 2026-02-27

Two branches existed: (001->...->006) and (v7_001->...->006_schema_contract_fix).
This merge revision has no schema changes; it only unifies the head for deployment.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "007_merge_heads"
down_revision: Union[str, Sequence[str], None] = ("006", "006_schema_contract_fix")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
