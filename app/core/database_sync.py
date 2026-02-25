"""
동기 DB 연결 (Celery 워커 전용). SQLAlchemy 2.0 + psycopg (sync).
FastAPI 웹은 asyncpg, 워커는 이 모듈만 사용해 "Too many connections" 방지.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

sync_engine = None
sync_session_factory = None


def _sync_database_url() -> str | None:
    """asyncpg URL을 동기 드라이버(psycopg3)용으로 변환. plain postgresql:// → +psycopg (psycopg2 미설치 시)."""
    raw = (settings.database_url or "").strip()
    if not raw:
        return None
    if "postgresql+asyncpg" in raw:
        return raw.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if raw.startswith("postgresql://") and "postgresql+" not in raw:
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    if "postgresql+psycopg" in raw:
        return raw
    return raw


def init_sync_db() -> None:
    """DATABASE_URL이 있으면 동기 엔진·세션 팩토리 초기화 (워커에서 호출)."""
    global sync_engine, sync_session_factory
    url = _sync_database_url()
    if not url:
        logger.warning("DATABASE_URL not set. Sync DB features disabled.")
        return

    from app.core.database import check_pool_budget

    effective_max_conn = settings.db_max_connections
    budget_result = check_pool_budget(effective_max_conn)
    if not budget_result.within_budget and budget_result.app_budget > 0:
        if settings.db_pool_strict_budget:
            raise RuntimeError(budget_result.message)
        logger.critical("%s", budget_result.message)

    pool_kw: dict = {
        "pool_size": settings.db_pool_size_sync,
        "max_overflow": settings.db_pool_max_overflow_sync,
        "pool_timeout": settings.db_pool_timeout_sync,
    }
    if settings.db_pool_recycle_sync >= 0:
        pool_kw["pool_recycle"] = settings.db_pool_recycle_sync

    sync_engine = create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        **pool_kw,
    )
    sync_session_factory = sessionmaker(
        bind=sync_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    """동기 세션 컨텍스트. 워커 태스크에서 with get_sync_session() as session: 형태로 사용."""
    if not sync_session_factory:
        init_sync_db()
    if not sync_session_factory:
        raise RuntimeError("Sync database not initialized. Set DATABASE_URL.")
    session = sync_session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
