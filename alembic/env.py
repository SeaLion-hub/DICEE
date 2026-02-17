"""Alembic 환경. 마이그레이션에만 psycopg(psycopg3) 동기 드라이버 사용. Windows+asyncpg 이슈·psycopg2 UnicodeDecodeError 마스킹 회피."""

import os
# PostgreSQL 클라이언트 인코딩 강제 (서버 응답 UTF-8 디코딩)
os.environ.setdefault("PGCLIENTENCODING", "UTF8")

from logging.config import fileConfig
from urllib.parse import unquote, urlparse

import psycopg

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.models import Base

# Alembic Config
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _to_psycopg_url(url: str) -> str:
    """postgresql+asyncpg:// -> postgresql+psycopg:// (마이그레이션 전용, psycopg3)."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _url_to_connect_args(url: str) -> dict:
    """URL 파싱 → psycopg connect 인자. 포트 등이 URL 파서에서 누락되는 경우 방지."""
    u = urlparse(url)
    if not u.hostname:
        raise ValueError("Invalid DATABASE_URL: missing host")
    dbname = (u.path or "/").lstrip("/").split("?")[0] or "postgres"
    return {
        "host": u.hostname,
        "port": int(u.port) if u.port else 5432,
        "user": unquote(u.username) if u.username else "postgres",
        "password": unquote(u.password) if u.password else "",
        "dbname": dbname,
    }


def get_url() -> str:
    """마이그레이션용 DB URL. DATABASE_URL 필수."""
    url = settings.database_url
    if not url:
        raise ValueError("DATABASE_URL not set. Set it in .env or environment.")
    url = url.strip()
    # 공백·줄바꿈·의심 문자열 검사 (터미널 출력이 .env에 붙어넣어졌을 때)
    bad = [" ", "\n", "\r", "alembic", "venv", "activate", "upgrade", "head"]
    for s in bad:
        if s in url.lower():
            raise ValueError(
                f"DATABASE_URL contains invalid characters (found '{s}'). "
                "Check .env: DATABASE_URL must be on a single line, e.g. "
                "postgresql+asyncpg://postgres:PASSWORD@localhost:5433/dicee"
            )
    return url


def run_migrations_offline() -> None:
    """오프라인 모드: SQL 스크립트 생성."""
    url = _to_psycopg_url(get_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인 모드: 마이그레이션만 psycopg(psycopg3)로 실행. 앱 런타임(실제 요청 처리)과 분리됨."""
    url = get_url()
    conn_args = _url_to_connect_args(url)
    # psycopg3: 실제 오류 메시지 표시 (psycopg2는 연결 실패 시 UnicodeDecodeError로 마스킹됨)
    # creator로 psycopg.connect() 직접 호출 → host/port/user/password/dbname 확실히 적용
    connectable = create_engine(
        "postgresql+psycopg://",
        poolclass=pool.NullPool,
        creator=lambda: psycopg.connect(**conn_args),
    )
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    except BaseException as e:
        import sys
        err_type = type(e).__name__
        err_msg = str(e)[:300]
        sys.stderr.write(f"[alembic] connect error: {err_type}: {err_msg}\n")
        if isinstance(e, UnicodeDecodeError):
            sys.stderr.write(
                "[hint] PostgreSQL password: use ASCII-only. See docs/DEPLOYMENT.md\n"
            )
        elif "OperationalError" in err_type or "connection" in err_msg.lower():
            sys.stderr.write(
                "[hint] DATABASE_URL: system env overrides .env. Check: echo $env:DATABASE_URL. "
                "Unset or set correctly. For Railway: use DATABASE_PUBLIC_URL in .env.\n"
            )
        sys.stderr.flush()
        raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
