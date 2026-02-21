"""Refactor notice schema: add dates/eligibility, remove old columns

Revision ID: 005
Revises: 534657f22f86
Create Date: 2026-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, Sequence[str], None] = '534657f22f86' # published_at 추가했던 버전
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 새로운 JSONB 컬럼 추가 (핵심)
    op.add_column('notices', sa.Column('images', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('notices', sa.Column('attachments', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('notices', sa.Column('dates', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('notices', sa.Column('eligibility', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # 2. 더 이상 쓰지 않는 옛날 컬럼 삭제
    # Note: If these columns don't exist, this might fail. I'll check notice model.
    op.drop_column('notices', 'deadline')
    op.drop_column('notices', 'event_start')
    op.drop_column('notices', 'event_end')
    op.drop_column('notices', 'event_title')
    op.drop_column('notices', 'poster_image_url')


def downgrade() -> None:
    # 롤백 시 복구 (필요시)
    op.add_column('notices', sa.Column('poster_image_url', sa.VARCHAR(length=2048), autoincrement=False, nullable=True))
    op.add_column('notices', sa.Column('event_title', sa.VARCHAR(length=512), autoincrement=False, nullable=True))
    op.add_column('notices', sa.Column('event_end', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('notices', sa.Column('event_start', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('notices', sa.Column('deadline', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    
    op.drop_column('notices', 'eligibility')
    op.drop_column('notices', 'dates')
    op.drop_column('notices', 'attachments')
    op.drop_column('notices', 'images')
