"""ingestion_attempt_repository 동기 경로 회귀."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.models.ingestion_attempt import IngestionAttempt
from app.repositories import ingestion_attempt_repository as repo
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Update as SAUpdate
from sqlalchemy.sql.selectable import Select


def test_increment_attempt_completed_batches_uses_atomic_update() -> None:
    aid = uuid.uuid4()
    session = MagicMock()
    refreshed = MagicMock(spec=IngestionAttempt)

    def _exec(stmt: object, *_a: object, **_kw: object):
        if isinstance(stmt, SAUpdate):
            return MagicMock(rowcount=1)
        if isinstance(stmt, Select):
            r = MagicMock()
            r.scalar_one_or_none.return_value = refreshed
            return r
        return MagicMock()

    session.execute.side_effect = _exec

    out = repo.increment_attempt_completed_batches_sync(session, aid)

    assert out is refreshed
    assert session.execute.call_count == 2
    first = session.execute.call_args_list[0][0][0]
    assert isinstance(first, SAUpdate)


def test_try_begin_rolls_back_nested_on_integrity_error() -> None:
    college_id = uuid.uuid4()
    session = MagicMock()
    src = MagicMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: src),
        MagicMock(scalar_one_or_none=lambda: None),
    ]

    nested = MagicMock()
    nested.__enter__ = MagicMock(return_value=None)
    nested.__exit__ = MagicMock(return_value=None)
    session.begin_nested.return_value = nested
    session.flush = MagicMock(side_effect=IntegrityError("stmt", {}, Exception()))

    out = repo.try_begin_ingestion_attempt_sync(session, college_source_id=college_id, celery_task_id="t1")

    assert out is None
    session.begin_nested.assert_called_once()
    session.flush.assert_called_once()
