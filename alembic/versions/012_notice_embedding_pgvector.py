"""Notice에 pgvector embedding(768) 컬럼 및 코사인 HNSW 인덱스 추가.

Revision ID: 012_notice_embedding
Revises: 011_notices_list_id
Create Date: 2026-03-28

downgrade는 확장(DROP EXTENSION) 없이 인덱스·컬럼만 제거한다.

컬럼 차원(768)은 app.constants.embeddings.EMBEDDING_DIM과 일치해야 한다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012_notice_embedding"
down_revision: str | Sequence[str] | None = "011_notices_list_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("ALTER TABLE notices ADD COLUMN embedding vector(768);")
    # Railway 등 statement_timeout(예: 30s)이면 대량 행에서 HNSW 생성이 끊길 수 있음.
    op.execute("SET LOCAL statement_timeout = 0;")
    op.execute(
        """
        CREATE INDEX ix_notices_embedding_hnsw_cosine ON notices
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL statement_timeout = 0;")
    op.drop_index("ix_notices_embedding_hnsw_cosine", table_name="notices")
    op.drop_column("notices", "embedding")
