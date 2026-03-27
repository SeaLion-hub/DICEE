"""Alembic 환경. 마이그레이션에 psycopg(psycopg3) 동기 드라이버만 사용.

Single migrator: release/migrate job must run one at a time. PostgreSQL advisory lock (ALEMBIC_ADVISORY_LOCK_ID)
prevents concurrent alembic upgrade head from multiple release processes.
"""

# ruff: noqa: I001

import json
import os
import sys
import time
from pathlib import Path
# PostgreSQL 클라이언트 인코딩 강제 (서버 응답 UTF-8 디코딩)
os.environ.setdefault("PGCLIENTENCODING", "UTF8")
# 마이그레이션 전용: APP_ENTRY 미설정 시 Settings 검증 통과 (배포 파이프라인에서 alembic만 실행할 때)
os.environ.setdefault("APP_ENTRY", "migrate")

from logging.config import fileConfig
from urllib.parse import unquote, urlparse

import psycopg

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.exc import OperationalError

# Advisory lock ID for single migrator. Only one process can hold this lock; prevents duplicate migration runs.
ALEMBIC_ADVISORY_LOCK_ID = int(os.environ.get("ALEMBIC_ADVISORY_LOCK_ID", "1296183890"))

from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402

# Alembic Config
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def process_revision_directives(context, revision, directives):
    if getattr(config.cmd_opts, "autogenerate", False):
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            print("[alembic] No schema changes detected; empty revision skipped.")


def _to_psycopg_url(url: str) -> str:
    """postgresql:// 또는 legacy asyncpg URL → postgresql+psycopg:// (마이그레이션 전용)."""
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
    """마이그레이션용 DB URL. 앱과 동일하게 settings.db.database_url 사용."""
    url = settings.db.database_url or ""
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
        compare_type=True,
        compare_server_default=True,
        process_revision_directives=process_revision_directives,
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
        # region agent log
        _dbg_path = Path(__file__).resolve().parent.parent / "debug-bbd2f1.log"
        try:
            with _dbg_path.open("a", encoding="utf-8") as _df:
                _df.write(
                    json.dumps(
                        {
                            "sessionId": "bbd2f1",
                            "hypothesisId": "H1",
                            "location": "alembic/env.py:run_migrations_online",
                            "message": "alembic_connect_attempt_start",
                            "data": {
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts,
                                "host": conn_args.get("host"),
                                "port": conn_args.get("port"),
                            },
                            "timestamp": int(time.time() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass
        # endregion agent log
        try:
            connectable = create_engine(
                "postgresql+psycopg://",
                poolclass=pool.NullPool,
                creator=lambda: psycopg.connect(**conn_args),
            )
            with connectable.connect() as connection:
                # Serialize migration: only one process may run alembic upgrade at a time.
                lock_acquired = connection.execute(
                    text("SELECT pg_try_advisory_lock(:lid)"), {"lid": ALEMBIC_ADVISORY_LOCK_ID}
                ).scalar()
                if not lock_acquired:
                    lock_wait_sec = float(os.environ.get("ALEMBIC_LOCK_WAIT_SEC", "30"))
                    lock_retries = int(os.environ.get("ALEMBIC_LOCK_RETRIES", "6"))
                    for _ in range(lock_retries):
                        time.sleep(lock_wait_sec)
                        lock_acquired = connection.execute(
                            text("SELECT pg_try_advisory_lock(:lid)"), {"lid": ALEMBIC_ADVISORY_LOCK_ID}
                        ).scalar()
                        if lock_acquired:
                            break
                    if not lock_acquired:
                        sys.stderr.write(
                            "[alembic] Could not acquire advisory lock; another migrator may be running. Exit.\n"
                        )
                        sys.stderr.flush()
                        sys.exit(1)
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    compare_type=True,
                    compare_server_default=True,
                    process_revision_directives=process_revision_directives,
                )
                with context.begin_transaction():
                    context.run_migrations()
            # region agent log
            try:
                with _dbg_path.open("a", encoding="utf-8") as _df:
                    _df.write(
                        json.dumps(
                            {
                                "sessionId": "bbd2f1",
                                "hypothesisId": "H1",
                                "location": "alembic/env.py:run_migrations_online",
                                "message": "alembic_connect_and_migrations_ok",
                                "data": {"attempt": attempt + 1},
                                "timestamp": int(time.time() * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except OSError:
                pass
            # endregion agent log
            return
        except OperationalError as e:
            last_error = e
            # region agent log
            try:
                with _dbg_path.open("a", encoding="utf-8") as _df:
                    _df.write(
                        json.dumps(
                            {
                                "sessionId": "bbd2f1",
                                "hypothesisId": "H2",
                                "location": "alembic/env.py:run_migrations_online",
                                "message": "alembic_operational_error",
                                "data": {
                                    "attempt": attempt + 1,
                                    "exc_type": type(e).__name__,
                                    "exc_prefix": str(e)[:400],
                                },
                                "timestamp": int(time.time() * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except OSError:
                pass
            # endregion agent log
            if attempt < max_attempts - 1:
                delay = min(initial_delay * (2**attempt), max_delay)
                sys.stderr.write(
                    "[alembic] connect attempt "
                    f"{attempt + 1}/{max_attempts} failed, retry in {delay:.0f}s: "
                    f"{type(e).__name__}: {str(e)[:200]}\n"
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
