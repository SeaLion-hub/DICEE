"""텍스트 임베딩 차원·모델 ID 단일 소스 (Notice.embedding, Alembic, 검색·백필과 일치해야 함)."""

# Gemini text-embedding-004 출력 차원. DB 컬럼 vector(N)·마이그레이션 DDL의 N과 동일해야 함.
EMBEDDING_DIM: int = 768

# google.generativeai.embed_content model 인자
GEMINI_EMBEDDING_MODEL: str = "models/text-embedding-004"
