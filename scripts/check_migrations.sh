#!/usr/bin/env sh
# Run from repository root with DATABASE_URL set (PostgreSQL + pgvector).
set -e
alembic upgrade head
alembic check
