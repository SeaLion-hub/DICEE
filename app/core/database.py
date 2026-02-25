"""비동기 DB 연결 및 세션 관리. SQLAlchemy 2.0 + psycopg(또는 asyncpg)."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
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


class Propagation(str, Enum):
    """중첩 트랜잭션 전파 정책. SessionScope에서만 사용."""

    REQUIRED = "required"  # 기존 세션 참여, 없으면 새로 생성. 내부 commit/rollback은 외부에 전파하지 않음.
    REQUIRES_NEW = "requires_new"  # 항상 새 세션. 독립 commit/rollback. ContextVar에 넣지 않음.
    NESTED = "nested"  # 기존 세션 있으면 savepoint, 없으면 REQUIRED와 동일.


# Holder: 테스트에서 오버라이드 가능. 전역 뮤테이션 대신 getter로 접근.
class _DbHolder:
    engine: AsyncEngine | None = None
    async_session_maker: async_sessionmaker[AsyncSession] | None = None


_db_holder = _DbHolder()

# verify_db_connection()에서 조회한 DB max_connections. check_pool_budget 오버라이드용.
_resolved_max_connections: int | None = None

# 프로파일 R (권장 풀 크기 참고용). 예산 검사는 settings 사용. DEPLOYMENT.md, docs/decisions/database-pool-capacity.md.
POOL_PROFILE_R = (4, 6, 2, 0)  # (P_async, O_async, P_sync, O_sync)


@dataclass(frozen=True)
class PoolBudgetResult:
    """풀 예산 검사 결과. 실제 풀 설정값 기준 Peak_pool_conn vs App_budget."""

    within_budget: bool
    app_budget: int
    total_pool_conn: int
    peak_pool_conn: int
    message: str


def check_pool_budget(effective_max_conn: int | None) -> PoolBudgetResult:
    """
    풀 예산 검사(실제 설정값 기준). effective_max_conn이 None이면 검사 생략(within_budget=True, 0 값 반환).
    산식: App_budget = floor((max_conn - DB_RESERVED) * 0.7),
    API_conn = N_api * N_uvicorn_workers * (db_pool_size_async + db_pool_max_overflow_async),
    Worker_conn = N_worker * N_celery_concurrency * (db_pool_size_sync + db_pool_max_overflow_sync),
    Total = API_conn + Worker_conn, Peak = Total * DEPLOY_SURGE_FACTOR.
    통과 조건: Peak_pool_conn <= App_budget.
    """
    if effective_max_conn is None or effective_max_conn < 1:
        return PoolBudgetResult(
            within_budget=True,
            app_budget=0,
            total_pool_conn=0,
            peak_pool_conn=0,
            message="Pool budget check skipped (no effective max_connections).",
        )
    reserved = settings.db_reserved
    app_budget = int((effective_max_conn - reserved) * 0.7)
    api_conn = (
        settings.db_api_instances
        * settings.db_uvicorn_workers
        * (settings.db_pool_size_async + settings.db_pool_max_overflow_async)
    )
    worker_conn = (
        settings.db_worker_instances
        * settings.db_celery_concurrency
        * (settings.db_pool_size_sync + settings.db_pool_max_overflow_sync)
    )
    total_pool_conn = api_conn + worker_conn
    peak_pool_conn = int(total_pool_conn * settings.deploy_surge_factor)
    within_budget = peak_pool_conn <= app_budget
    if within_budget:
        msg = (
            f"Pool budget OK: peak={peak_pool_conn} <= app_budget={app_budget} "
            f"(total={total_pool_conn}, max_conn={effective_max_conn})."
        )
    else:
        msg = (
            f"Pool budget exceeded: peak_pool_conn={peak_pool_conn} > app_budget={app_budget}. "
            "Adjust DB_API_INSTANCES or DB_MAX_CONNECTIONS. See DEPLOYMENT.md."
        )
    return PoolBudgetResult(
        within_budget=within_budget,
        app_budget=app_budget,
        total_pool_conn=total_pool_conn,
        peak_pool_conn=peak_pool_conn,
        message=msg,
    )


def get_resolved_max_connections() -> int | None:
    """부팅 시 DB에서 조회한 max_connections. 미조회 시 None."""
    return _resolved_max_connections


# SessionScope를 통해서만 set/reset. 직접 _session_context.set/reset 호출 금지.
# 요청 경로: Depends(get_db)로 세션 주입 후 서비스에 인자로 전달(권장). 비요청 경로(Celery 등): run_in_session만 사용.
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

    # 2. 비동기 드라이버 자동 적용 (drivername 미지정 시 여기서 설정. 배포 시 postgresql+psycopg 권장 — DEPLOYMENT.md)
    if "asyncpg" not in parsed.drivername and "psycopg" not in parsed.drivername:
        parsed = parsed.set(drivername="postgresql+psycopg")

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
    raw_url = (settings.database_url or "").strip()
    if not raw_url:
        logger.warning("DATABASE_URL not set or empty. DB features disabled.")
        return

    # 배포 환경 디버깅: 앱이 실제로 쓰는 호스트만 로그 (비밀번호·user 제외). warning으로 해야 Railway stderr에 출력됨.
    try:
        parsed = make_url(raw_url)
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

    # 연결 단위 statement_timeout 적용. docs/decisions/database-pool-capacity.md.
    # psycopg3 (postgresql+psycopg)는 server_settings 미지원 → libpq options 사용.
    connect_args: dict = {}
    timeout_ms = getattr(settings, "db_statement_timeout_ms", 30000)
    connect_args["options"] = f"-c statement_timeout={timeout_ms}"

    _db_holder.engine = create_async_engine(
        _async_database_url(raw_url),
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

    global _resolved_max_connections
    for attempt in range(1, retries + 1):
        try:
            async with maker() as session:
                await session.execute(text("SELECT 1"))
                try:
                    result = await session.execute(
                        text("SELECT current_setting('max_connections')::int")
                    )
                    val = result.scalar_one_or_none()
                    if val is not None:
                        _resolved_max_connections = int(val)
                except Exception as e:
                    logger.debug("Could not fetch max_connections: %s", e)
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
                {
                    "url_set": bool((settings.database_url or "").strip()),
                    "retries": retries,
                },
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
            f"Database connection failed after {retries} attempts: {last_exc}"
        ) from last_exc


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends용 비동기 DB 세션 생성기. app.state.async_session_maker 단일 경로만 사용.
    """
    maker = getattr(request.app.state, "async_session_maker", None)
    if not maker:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    async with maker() as session:
        yield session


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession] | None,
    propagation: Propagation = Propagation.REQUIRED,
) -> AsyncGenerator[AsyncSession, None]:
    """
    세션 스코프. ContextVar는 이 매니저를 통해서만 set/reset됨.
    REQUIRED: 기존 세션 참여 또는 새로 생성(commit/rollback 소유).
    REQUIRES_NEW: 항상 새 세션, 독립 commit/rollback.
    NESTED: 기존 세션 있으면 savepoint, 없으면 REQUIRED와 동일.
    """
    if not session_factory:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")

    existing = _session_context.get()
    if propagation == Propagation.REQUIRED and existing is not None:
        yield existing
        return

    if propagation == Propagation.NESTED and existing is not None:
        async with existing.begin_nested():
            yield existing
        return

    # REQUIRES_NEW 또는 REQUIRED/NESTED에서 기존 세션 없음: 새 세션 생성
    session: AsyncSession | None = None
    token: Any = None
    try:
        session = session_factory()
        if propagation == Propagation.REQUIRED:
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


@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession, None]:
    """서비스 레이어용 트랜잭션. SessionScope(REQUIRED) 호환 레이어."""
    maker = get_async_session_maker()
    async with session_scope(maker, Propagation.REQUIRED) as session:
        yield session


async def run_in_session(
    session_factory: async_sessionmaker[AsyncSession] | None,
    fn: Callable[[AsyncSession], Awaitable[Any]],
) -> Any:
    """
    비요청 컨텍스트(Celery 등)에서 단일 진입점. 세션 생성 후 fn(session) 호출.
    fn은 async def(session) 시그니처. 전역 상태에 손대지 않고 세션만 명시 전달.
    """
    if not session_factory:
        raise RuntimeError("Database not initialized. Set DATABASE_URL.")
    async with session_scope(session_factory, Propagation.REQUIRES_NEW) as session:
        return await fn(session)
