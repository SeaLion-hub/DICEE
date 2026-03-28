"""통합 테스트: pgvector 코사인 거리 정렬 (실 DB). DATABASE_URL 없으면 skip."""

import asyncio
import os
import sys
from datetime import UTC, datetime

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

pytest.importorskip("sqlalchemy.ext.asyncio")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def _ensure_async_db():
    if not (os.environ.get("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL not set; integration test skipped")
    from app.core.database import init_db

    init_db()


def _unit(dim: int, idx: int) -> list[float]:
    v = [0.0] * dim
    v[idx] = 1.0
    return v


@pytest.mark.asyncio
async def test_search_notices_by_embedding_orders_by_cosine_distance(_ensure_async_db):
    """동일 college·기간 내에서 쿼리 벡터와 가장 가까운 공지가 먼저 온다."""
    from app.constants.embeddings import EMBEDDING_DIM
    from app.core.database import get_async_session_maker
    from app.models.college import College
    from app.models.notice import Notice
    from app.repositories.notice_repository import search_notices_by_embedding
    from sqlalchemy import select

    maker = get_async_session_maker()
    if not maker:
        pytest.skip("Async session maker not initialized")

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2027, 1, 1, tzinfo=UTC)
    u0 = _unit(EMBEDDING_DIM, 0)
    u1 = _unit(EMBEDDING_DIM, 1)

    async with maker() as session:
        result = await session.execute(select(College).where(College.external_id == "integration-embed-college"))
        college = result.scalar_one_or_none()
        if college is None:
            college = College(name="Embed Test College", external_id="integration-embed-college")
            session.add(college)
            await session.flush()

        cid = college.id
        for ext, emb in (("embed-a", u0), ("embed-b", u1)):
            existing = await session.execute(select(Notice).where(Notice.college_id == cid, Notice.external_id == ext))
            row = existing.scalar_one_or_none()
            if row is None:
                n = Notice(
                    college_id=cid,
                    external_id=ext,
                    title=f"Title {ext}",
                    published_at=datetime(2026, 6, 1, tzinfo=UTC),
                    embedding=emb,
                )
                session.add(n)
            else:
                row.embedding = emb
                row.published_at = datetime(2026, 6, 1, tzinfo=UTC)
        await session.commit()

    async with maker() as session:
        ordered = await search_notices_by_embedding(
            session,
            college_id=cid,
            published_from=t0,
            published_to=t1,
            query_embedding=u0,
            limit=10,
        )
        ids = [n.external_id for n in ordered if n.external_id in ("embed-a", "embed-b")]
        assert ids[:2] == ["embed-a", "embed-b"]

    async with maker() as session:
        ordered_b = await search_notices_by_embedding(
            session,
            college_id=cid,
            published_from=t0,
            published_to=t1,
            query_embedding=u1,
            limit=10,
        )
        ids_b = [n.external_id for n in ordered_b if n.external_id in ("embed-a", "embed-b")]
        assert ids_b[:2] == ["embed-b", "embed-a"]
