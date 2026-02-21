"""비동기 DB 연결 및 세션 관리. SQLAlchemy 2.0 + asyncpg."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# Holder: 테스트에서 오버라이드 가능. 전역 뮤테이션 대신 getter로 접근.
class _DbHolder:
    engine: AsyncEngine | None = None
    async_session_maker: async_sessionmaker[AsyncSession] | None = None


_db_holder = _DbHolder()

# 동일 컨텍스트 내 세션 전파. transaction() 진입 시 set, finally에서 reset(token)으로 누수 방지.
_session_context: ContextVar[AsyncSession | None] = ContextVar(
    "session_context", default=None
)


def _async_database_url(url: str) -> str:
    """FastAPI용: 스킴만 asyncpg로 안전하게 변환. SQLAlchemy make_url 사용."""
    return str(make_url(url.strip()).set(drivername="postgresql+asyncpg"))


def get_engine() -> AsyncEngine | None:
    """현재 엔진. 테스트에서 override_db_for_testing 후에는 테스트 엔진 반환."""
    return _db_holder.engine


def get_async_session_maker() -> async_sessionmaker[AsyncSession] | None:
    """현재 세션 팩토리. 테스트에서 override_db_for_testing 후에는 테스트 팩토리 반환."""
    return _db_holder.async_session_maker


def init_db() -> None:
    """DATABASE_URL이 있으면 엔진·세션 팩토리 초기화. Holder에 설정."""
    if not settings.database_url:
        logger.warning("DATABASE_URL not set. DB features disabled.")
        return

    _db_holder.engine = create_async_engine(
        _async_database_url(settings.database_url),
        echo=False,
        pool_pre_ping=True,
    )
    _db_holder.async_session_maker = async_sessionmaker(
        _db_holder.engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


def override_db_for_testing(
    engine: AsyncEngine | None = None,
    async_session_maker_instance: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """테스트용. Holder를 테스트 엔진/세션 팩토리로 교체. pytest-xdist 등 병렬 테스트 격리용."""
    _db_holder.engine = engine
    _db_holder.async_session_maker = async_session_maker_instance


async def verify_db_connection() -> None:
    """
    DB 연결 검증. 실패 시 재시도 후 예외 전파 또는 Sentry 보고 후 부팅 중단.
    컨테이너 환경(Railway)에서 DB가 일시적으로 준비 안 된 경우 대비.
    CAUTIONS: except Exception으로 덮어두지 않음.
    """
    maker = get_async_session_maker()
    if not _db_holder.engine or not maker:
        return

    last_exc: Exception | None = None
    retries = max(1, settings.db_connect_retries)
    interval = max(0.5, settings.db_connect_retry_interval_sec)

    for attempt in range(1, retries + 1):
        try:
            async with maker() as session:
                await session.execute(text("SELECT 1"))
            return
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                logger.warning(
                    "Database connection attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt,
                    retries,
                    exc,
                    interval,
                )
                await asyncio.sleep(interval)
            else:
                break

    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("context", "database_connection_check")
            scope.set_context(
                "database",
                {"url_set": bool(settings.database_url), "retries": retries},
            )
            sentry_sdk.capture_exception(last_exc)
    except ImportError:
        pass

    logger.critical(
        "Database connection failed after %d attempts: %s. Aborting startup.",
        retries,
        last_exc,
        exc_info=True,
    )
    raise RuntimeError(
        "Database connection failed after %d attempts: %s" % (retries, last_exc)
    ) from last_exc


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends용 비동기 DB 세션 생성기. 읽기 전용/단일 쿼리용.
    트랜잭션 경계는 서비스 레이어의 transaction() 컨텍스트 매니저에서만 제어한다.
    """
    maker = get_async_session_maker()
    if not maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    async with maker() as session:
        yield session


@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession, None]:
    """
    서비스 레이어용 트랜잭션 컨텍스트 매니저. 성공 시 commit, 예외 시 rollback.
    동일 컨텍스트 내 중첩 호출 시 ContextVar로 세션 공유(하나의 트랜잭션).
    예외 발생 여부와 무관하게 finally에서 ContextVar.reset(token) 호출로 커넥션 풀 누수 방지.
    """
    maker = get_async_session_maker()
    if not maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    existing = _session_context.get()
    if existing is not None:
        # 이미 상위에서 transaction()이 열린 경우 같은 세션 재사용. commit/rollback은 최외곽에서만.
        yield existing
        return

    session: AsyncSession | None = None
    token: Any = None
    try:
        session = maker()
        token = _session_context.set(session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    finally:
        # 반드시 reset으로 컨텍스트 복원. 누수 방지.
        if token is not None:
            _session_context.reset(token)
        if session is not None:
            await session.close()
