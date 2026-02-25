"""CrawlRun Repository 계약 검증: run_id당 1행 전제, id 단독 조회/갱신."""

import os
import uuid

import pytest
from sqlalchemy import select

from app.models.crawl_run import CrawlRun
from app.repositories.crawl_run_repository import (
    create_or_update_crawl_run_sync,
    update_crawl_run_sync,
)


@pytest.fixture(scope="module")
def _ensure_sync_db():
    """DATABASE_URL이 없으면 skip."""
    if not (os.environ.get("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL not set; integration test skipped")
    from app.core.database_sync import init_sync_db

    init_sync_db()


def test_crawl_run_single_row_per_run_id_contract(_ensure_sync_db):
    """
    계약: 동일 run_id로 create_or_update_crawl_run_sync를 두 번 호출하면
    한 행만 존재하고, 두 번째 호출은 기존 행을 갱신해 반환한다.
    update_crawl_run_sync는 id 단독으로 해당 행을 찾아 갱신한다.
    """
    from app.core.database_sync import get_sync_session
    from app.models.college import College

    run_id = uuid.uuid4()
    with get_sync_session() as session:
        result = session.execute(select(College).limit(1))
        college = result.scalar_one_or_none()
        if not college:
            college = College(
                name="CrawlRun Contract Test College",
                external_id="crawl-run-contract-test",
            )
            session.add(college)
            session.flush()

        row1 = create_or_update_crawl_run_sync(session, run_id, college.id)
        assert row1 is not None
        assert row1.id == run_id
        assert row1.status == "running"

        row2 = create_or_update_crawl_run_sync(session, run_id, college.id)
        assert row2 is not None
        assert row2.id == run_id
        assert row1.id == row2.id

        count = session.execute(select(CrawlRun).where(CrawlRun.id == run_id)).scalars().all()
        assert len(count) == 1, "run_id당 1행 계약: 동일 id로 복수 행이 생기면 안 됨"

        updated = update_crawl_run_sync(session, run_id, status="success")
        assert updated is not None
        assert updated.status == "success"

        session.rollback()
