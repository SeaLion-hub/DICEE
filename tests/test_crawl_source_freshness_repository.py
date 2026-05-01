from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.repositories.crawl_run_repository import fetch_source_freshness_async
from sqlalchemy.dialects import postgresql


class _Result:
    def all(self) -> list[tuple[object, ...]]:
        return [
            ("engineering", "success", datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 1, tzinfo=UTC), 12),
            ("science", None, None, None, None),
        ]


class _Session:
    def __init__(self) -> None:
        self.execute_count = 0
        self.statement = None

    async def execute(self, stmt: object) -> _Result:
        self.execute_count += 1
        self.statement = stmt
        return _Result()

    async def scalar(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("fetch_source_freshness_async must not issue per-source scalar queries")


@pytest.mark.asyncio
async def test_fetch_source_freshness_uses_single_distinct_on_query() -> None:
    session = _Session()

    rows = await fetch_source_freshness_async(session)

    assert session.execute_count == 1
    sql = str(session.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
    assert "DISTINCT ON" in sql
    assert [r.college_code for r in rows] == ["engineering", "science"]
    assert rows[0].last_attempt_status == "success"
    assert rows[0].total_docs == 12
    assert rows[1].last_attempt_status is None
