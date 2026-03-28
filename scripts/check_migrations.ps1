# Run from repository root with DATABASE_URL set (PostgreSQL + pgvector).
$ErrorActionPreference = "Stop"
alembic upgrade head
alembic check
