"""비동기 DB 연결 및 세션 관리. SQLAlchemy 2.0 + asyncpg."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = None
async_session_maker = None


def _async_database_url(url: str) -> str:
    """FastAPI용: 스킴만 asyncpg로 안전하게 변환. SQLAlchemy make_url 사용."""
    return str(make_url(url.strip()).set(drivername="postgresql+asyncpg"))


def init_db() -> None:
    """DATABASE_URL이 있으면 엔진·세션 팩토리 초기화."""
    global engine, async_session_maker
    if not settings.database_url:
        logger.warning("DATABASE_URL not set. DB features disabled.")
        return

    engine = create_async_engine(
        _async_database_url(settings.database_url),
        echo=False,
        pool_pre_ping=True,
    )
    async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def verify_db_connection() -> None:
    """
    DB 연결 검증. 실패 시 재시도 후 예외 전파 또는 Sentry 보고 후 부팅 중단.
    컨테이너 환경(Railway)에서 DB가 일시적으로 준비 안 된 경우 대비.
    CAUTIONS: except Exception으로 덮어두지 않음.
    """
    if not engine or not async_session_maker:
        return

    last_exc: Exception | None = None
    retries = max(1, settings.db_connect_retries)
    interval = max(0.5, settings.db_connect_retry_interval_sec)

    for attempt in range(1, retries + 1):
        try:
            async with async_session_maker() as session:
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
    if not async_session_maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    async with async_session_maker() as session:
        yield session


@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession, None]:
    """
    서비스 레이어용 트랜잭션 컨텍스트 매니저. 성공 시 commit, 예외 시 rollback.
    비즈니스 로직은 이 안에서만 DB 쓰기 시 수행한다.
    """
    if not async_session_maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
