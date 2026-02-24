"""비동기 DB 연결 및 세션 관리. SQLAlchemy 2.0 + asyncpg."""

import asyncio
import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from fastapi import Request
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
    """FastAPI용: 스킴을 비동기 드라이버로 안전하게 변환하고 비밀번호 마스킹을 방지합니다."""
    raw_url = url.strip()
    
    # 1. 다이얼렉트 스킴 동적 정규화 (postgres:// -> postgresql://)
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)
        
    parsed = make_url(raw_url)
    
    # 2. 비동기 드라이버 자동 적용
    if "asyncpg" not in parsed.drivername and "psycopg" not in parsed.drivername:
        parsed = parsed.set(drivername="postgresql+asyncpg")
        
    # 3. 핵심 픽스: str() 사용 시 비밀번호가 '***'로 마스킹되는 것을 방지
    # 반드시 hide_password=False 옵션으로 진짜 비밀번호를 반환해야 합니다.
    return parsed.render_as_string(hide_password=False)


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

    # 배포 환경 디버깅: 앱이 실제로 쓰는 호스트만 로그 (비밀번호·user 제외). warning으로 해야 Railway stderr에 출력됨.
    try:
        parsed = make_url(settings.database_url.strip())
        has_username = bool(parsed.username)
        has_password = bool(parsed.password)
        logger.warning(
            "DB connect: host=%s port=%s dbname=%s user_set=%s password_set=%s (DATABASE_URL set)",
            parsed.host or "(none)",
            parsed.port or 5432,
            (parsed.database or "/").lstrip("/") or "(default)",
            has_username,
            has_password,
        )
    except Exception as e:
        logger.warning("DB URL parse check failed: %s", e)

    from app.core.config import check_pool_budget

    within_budget, peak_conn, app_budget = check_pool_budget()
    if not within_budget and peak_conn > 0 and app_budget >= 0:
        msg = (
            f"Pool budget exceeded: peak_conn={peak_conn} > app_budget={app_budget}. "
            "Adjust pool sizes or DB_MAX_CONNECTIONS. See DEPLOYMENT.md."
        )
        if settings.db_pool_strict_budget:
            raise ValueError(msg)
        logger.warning(msg)

    connect_args: dict = {}
    
    _db_holder.engine = create_async_engine(
        _async_database_url(settings.database_url),
        echo=False,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size_async,
        max_overflow=settings.db_pool_max_overflow_async,
        pool_timeout=settings.db_pool_timeout_async,
        connect_args=connect_args,
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
        "Database connection failed after %d attempts: %s.",
        retries,
        last_exc,
        exc_info=True,
    )
    if settings.strict_startup_db_check:
        raise RuntimeError(
            "Database connection failed after %d attempts: %s" % (retries, last_exc)
        ) from last_exc


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends용 비동기 DB 세션 생성기.
    """
    maker = getattr(request.app.state, "async_session_maker", None) or get_async_session_maker()
    if not maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    async with maker() as session:
        yield session


@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession, None]:
    """
    서비스 레이어용 트랜잭션 컨텍스트 매니저. 성공 시 commit, 예외 시 rollback.
    """
    maker = get_async_session_maker()
    if not maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    existing = _session_context.get()
    if existing is not None:
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
        if token is not None:
            _session_context.reset(token)
        if session is not None:
            await session.close()
