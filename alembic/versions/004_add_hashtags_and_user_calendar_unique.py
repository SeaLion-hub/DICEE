"""add notices.hashtags, user_calendar_events unique constraint

Revision ID: 004
Revises: 003
Create Date: 2026-02-17

- notices.hashtags: 4단계 AI 출력(해시태그 배열). JSONB.
- user_calendar_events: UniqueConstraint(user_id, notice_id) — 한 공지 중복 추가 방지.
  기존에 (user_id, notice_id) 중복 행이 있으면 마이그레이션 전에 수동 제거 필요.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, Sequence[str], None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notices",
        sa.Column("hashtags", postgresql.JSONB(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_user_calendar_user_notice",
        "user_calendar_events",
        ["user_id", "notice_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_calendar_user_notice",
        "user_calendar_events",
        type_="unique",
    )
    op.drop_column("notices", "hashtags")
