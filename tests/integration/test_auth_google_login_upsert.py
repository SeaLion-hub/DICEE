"""통합 테스트: google_login -> upsert_by_provider_uid 실제 쿼리 경로.

User.deleted_at이 포함된 upsert 쿼리가 실행되는지 검증. DATABASE_URL 없으면 skip.
"""

import os

import pytest

pytest.importorskip("sqlalchemy.ext.asyncio")


@pytest.fixture(scope="module")
def _ensure_db():
    """DATABASE_URL이 없으면 skip."""
    if not (os.environ.get("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL not set; integration test skipped")
    from app.core.database import init_db

    init_db()


@pytest.mark.asyncio
async def test_upsert_by_provider_uid_runs_deleted_at_query_path(_ensure_db):
    """upsert_by_provider_uid 호출 시 User.deleted_at이 포함된 ON CONFLICT 쿼리가 실행됨."""
    from app.core.database import get_async_session_maker
    from app.repositories.user_repository import get_by_provider_uid, upsert_by_provider_uid
    from app.schemas.user import UserBase

    maker = get_async_session_maker()
    if not maker:
        pytest.skip("Async session maker not initialized")
    async with maker() as session:
        user = await upsert_by_provider_uid(
            session,
            "google",
            "integration-test-provider-uid",
            UserBase(email="integration@test.com", name="Integration Test"),
        )
        assert user is not None
        assert user.id is not None
        found = await get_by_provider_uid(session, "google", "integration-test-provider-uid")
        assert found is not None
        assert found.id == user.id
        await session.rollback()
