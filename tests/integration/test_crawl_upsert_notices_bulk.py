"""통합 테스트: crawl_college_sync -> upsert_notices_bulk_sync 실제 upsert 경로.

Notice.deleted_at이 포함된 bulk upsert 쿼리가 실행되는지 검증. DATABASE_URL 없으면 skip.
"""

import os

import pytest

from sqlalchemy import select


@pytest.fixture(scope="module")
def _ensure_sync_db():
    """DATABASE_URL이 없으면 skip."""
    if not (os.environ.get("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL not set; integration test skipped")
    from app.core.database_sync import init_sync_db

    init_sync_db()


def test_upsert_notices_bulk_sync_runs_deleted_at_query_path(_ensure_sync_db):
    """upsert_notices_bulk_sync 호출 시 Notice.deleted_at이 포함된 ON CONFLICT 쿼리가 실행됨."""
    from app.core.database_sync import get_sync_session
    from app.models.college import College
    from app.repositories.notice_repository import upsert_notices_bulk_sync

    with get_sync_session() as session:
        result = session.execute(select(College).limit(1))
        college = result.scalar_one_or_none()
        if not college:
            college = College(
                name="Integration Test College",
                external_id="integration-test-college",
            )
            session.add(college)
            session.flush()
        notice_payload = [
            {
                "college_id": college.id,
                "external_id": "integration-test-notice-1",
                "title": "Integration Test Notice",
                "url": "https://example.com/integration-test",
            }
        ]
        ids = upsert_notices_bulk_sync(session, notice_payload)
        assert isinstance(ids, list)
        session.rollback()
