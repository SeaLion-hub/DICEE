"""notice_schedules 동기 교체(모의 세션)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.domain.contracts.ai_extraction import ScheduleItem, ScheduleKind
from app.repositories.notice_schedule_repository import replace_notice_schedules_sync
from sqlalchemy.orm import Session


def test_replace_notice_schedules_sync_deletes_and_inserts() -> None:
    session = MagicMock(spec=Session)
    nid = uuid.uuid4()
    sched = ScheduleItem(
        kind=ScheduleKind.APPLICATION_DEADLINE,
        starts_at=datetime(2026, 4, 1, 15, 0, tzinfo=UTC),
        ends_at=None,
        label="마감",
    )
    replace_notice_schedules_sync(session, nid, [sched])
    session.execute.assert_called()
    session.bulk_insert_mappings.assert_called_once()
    session.flush.assert_called_once()
