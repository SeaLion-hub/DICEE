"""Integration test for the current pinned user_calendar_events schema."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

pytest.importorskip("sqlalchemy.ext.asyncio")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def _ensure_db():
    if not (os.environ.get("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL not set; integration test skipped")
    from app.core.database import init_db

    init_db()


@pytest.mark.asyncio
async def test_create_for_user_uses_current_pinned_event_shape(_ensure_db) -> None:
    from app.core.database import get_async_session_maker
    from app.models.college import College
    from app.models.notice import Notice
    from app.models.user import User
    from app.repositories.user_calendar_event_repository import create_for_user

    maker = get_async_session_maker()
    if not maker:
        pytest.skip("Async session maker not initialized")

    suffix = uuid.uuid4().hex
    async with maker() as session:
        college = College(
            name="Integration Calendar College",
            external_id=f"integration-calendar-college-{suffix}",
        )
        user = User(
            provider="google",
            provider_user_id=f"integration-calendar-user-{suffix}",
            email=None,
            name="Integration Calendar User",
        )
        notice = Notice(
            college=college,
            external_id=f"integration-calendar-notice-{suffix}",
            title="Integration Calendar Notice",
            ai_status="pending",
        )
        session.add_all([college, user, notice])
        await session.flush()

        row = await create_for_user(
            session,
            user_id=user.id,
            notice_id=notice.id,
            title="Pinned Event",
            start_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            end_at=None,
        )

        assert isinstance(row.id, int)
        assert row.notice_id == notice.id
        assert row.title == "Pinned Event"

        await session.rollback()
