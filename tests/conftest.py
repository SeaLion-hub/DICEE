"""Pytest fixtures. 테스트 시 DB 없이 실행 가능하도록 환경 조정."""

import asyncio
import importlib
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI

# CI에서 DATABASE_URL이 주입되면 그대로 사용. 로컬에서 비어 있으면 DB 없이 부팅 가능하도록 빈 문자열.
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = ""
# Celery 앱은 import 시점에 APP_ENTRY=celery 검사. 테스트 세션 전체에서 tasks/celery_app import 가능하도록 강제.
os.environ["APP_ENTRY"] = "celery"
# Settings Fail-fast 대비: 테스트 시 필수 Auth env 설정
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")

# 더미 세션 호출 순서 기록 — commit/rollback/execute 순서로 트랜잭션 회귀 검증용.
# 요청마다 _dummy_session_cm 진입 시 초기화. get_db를 override하지 않는 테스트에서 사용.
# commit/rollback 순서 assert 시 get_db override 후 세션 로그 검사 권장(예: test_logout_blocklist_*).
dummy_session_call_log: list[str] = []


def _clear_dummy_session_call_log() -> None:
    global dummy_session_call_log
    dummy_session_call_log = []


class _TrackingSession:
    """commit/rollback/execute 호출을 dummy_session_call_log에 기록하는 더미 세션. 트랜잭션 순서 검증용."""

    async def commit(self) -> None:
        dummy_session_call_log.append("commit")

    async def rollback(self) -> None:
        dummy_session_call_log.append("rollback")

    async def execute(self, *args: object, **kwargs: object):
        dummy_session_call_log.append("execute")
        return None


@asynccontextmanager
async def _dummy_session_cm():
    """DB 미사용 시 주입되는 더미 세션. commit/rollback/execute 호출을 기록해 트랜잭션 순서 검증 가능."""
    global dummy_session_call_log
    _clear_dummy_session_call_log()
    session = MagicMock()
    # AsyncMock await 시 side_effect만 호출·반환하므로, 로그는 동기 부수효과로 기록(코루틴 반환 시 미실행됨).
    session.commit = AsyncMock(side_effect=lambda: dummy_session_call_log.append("commit"))
    session.rollback = AsyncMock(side_effect=lambda: dummy_session_call_log.append("rollback"))

    async def _logged_execute(*args: object, **kwargs: object):
        dummy_session_call_log.append("execute")
        return None

    session.execute = _logged_execute
    yield session


def _dummy_session_maker(*_args: object, **_kwargs: object):
    """read_only_session_cm이 maker(execution_options=...)로 호출하므로 가변 인자 허용."""
    return _dummy_session_cm()


def _ensure_dummy_async_session_maker(app: object) -> None:
    """lifespan 후 DATABASE_URL 없으면 maker가 None일 수 있음. TestClient 진입·async 워밍업 직후 호출."""
    state = getattr(app, "state", None)
    if state is not None and getattr(state, "async_session_maker", None) is None:
        state.async_session_maker = _dummy_session_maker


@pytest.fixture
def api_app() -> "FastAPI":
    """APP_ENTRY=api로 로드한 단일 FastAPI 인스턴스. client·async_client·dependency_overrides 동일 앱."""
    import app.core.config as config_module

    with patch.dict(os.environ, {"APP_ENTRY": "api"}):
        importlib.reload(config_module)
        from app.main import app

        yield app
    with patch.dict(os.environ, {"APP_ENTRY": "celery"}):
        importlib.reload(config_module)


@pytest.fixture
def client(api_app: "FastAPI") -> TestClient:
    """동기 TestClient. lifespan 종료 후 더미 세션 메이커 주입(TestClient와 동일 계약)."""
    with TestClient(api_app) as c:
        _ensure_dummy_async_session_maker(c.app)
        yield c


@pytest_asyncio.fixture
async def async_client(api_app: "FastAPI") -> AsyncIterator[httpx.AsyncClient]:
    """비동기 httpx. 동일 api_app·lifespan 후 더미 maker로 read_only DB 경로 일치."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_app),
        base_url="http://test",
    ) as ac:
        await ac.get("/live")
        _ensure_dummy_async_session_maker(api_app)
        yield ac
