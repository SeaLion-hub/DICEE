"""Alembic 환경. 마이그레이션에만 psycopg(psycopg3) 동기 드라이버 사용. Windows+asyncpg 이슈·psycopg2 UnicodeDecodeError 마스킹 회피."""

import os
import time
# PostgreSQL 클라이언트 인코딩 강제 (서버 응답 UTF-8 디코딩)
os.environ.setdefault("PGCLIENTENCODING", "UTF8")

from logging.config import fileConfig
from urllib.parse import unquote, urlparse

import psycopg

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import OperationalError

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
    # Railway 등에서 DB 콜드스타트 시 연결 대기 시간 확보 (기본 90초)
    connect_timeout = int(os.environ.get("ALEMBIC_CONNECT_TIMEOUT", "90"))
    return {
        "host": u.hostname,
        "port": int(u.port) if u.port else 5432,
        "user": unquote(u.username) if u.username else "postgres",
        "password": unquote(u.password) if u.password else "",
        "dbname": dbname,
        "connect_timeout": connect_timeout,
    }


def get_url() -> str:
    """마이그레이션용 DB URL. 앱과 동일하게 오직 settings.database_url 단 하나만 사용합니다."""
    url = settings.database_url or ""
    if not url:
        raise ValueError(
            "DATABASE_URL not set. Set it in .env or environment."
        )
    url = url.strip()
    
    # 레거시 스킴 정규화 (app/core/database.py와 동일한 로직)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    # 공백·줄바꿈 검사
    for s in (" ", "\n", "\r"):
        if s in url:
            raise ValueError(
                "DATABASE_URL must not contain spaces or newlines. "
                "Check .env: DATABASE_URL must be on a single line."
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
    """온라인 모드: 마이그레이션만 psycopg(psycopg3)로 실행. Railway 등 DB 콜드스타트 대비 재시도."""
    url = get_url()
    conn_args = _url_to_connect_args(url)
    max_attempts = int(os.environ.get("ALEMBIC_RETRY_ATTEMPTS", "6"))
    initial_delay = float(os.environ.get("ALEMBIC_RETRY_INITIAL_SEC", "8"))
    max_delay = float(os.environ.get("ALEMBIC_RETRY_MAX_SEC", "40"))
    last_error = None
    for attempt in range(max_attempts):
        try:
            connectable = create_engine(
                "postgresql+psycopg://",
                poolclass=pool.NullPool,
                creator=lambda: psycopg.connect(**conn_args),
            )
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
            return
        except OperationalError as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = min(initial_delay * (2**attempt), max_delay)
                import sys
                sys.stderr.write(
                    f"[alembic] connect attempt {attempt + 1}/{max_attempts} failed, retry in {delay:.0f}s: {type(e).__name__}: {str(e)[:200]}\n"
                )
                sys.stderr.flush()
                time.sleep(delay)
            else:
                break
        except BaseException as e:
            last_error = e
            break
    e = last_error
    if e is not None:
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
                "Unset or set correctly.\n"
            )
        sys.stderr.flush()
        raise e


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
