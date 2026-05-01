"""notice_preprocess.pipeline sectionization and idempotency tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.services.notice_preprocess.pipeline import (
    DEFAULT_CLEANER_VERSION,
    apply_batch_preprocess_sync,
    sectionize_from_title_body,
)


def test_sectionize_from_title_body_title_only() -> None:
    assert sectionize_from_title_body(title="  Notice title  ") == [{"kind": "title", "text": "Notice title"}]


def test_sectionize_from_title_body_title_and_body() -> None:
    assert sectionize_from_title_body(title="Title", body_text="  Body text  ") == [
        {"kind": "title", "text": "Title"},
        {"kind": "body", "text": "Body text"},
    ]


def test_sectionize_from_title_body_whitespace_only_returns_empty() -> None:
    assert sectionize_from_title_body(title="   ", body_text="\n\t") == []


def test_sectionize_from_title_body_truncates_long_body() -> None:
    body = "x" * 50_010

    sections = sectionize_from_title_body(title="", body_text=body)

    assert sections == [{"kind": "body", "text": "x" * 50_000}]


def _notice(*, title: str, deleted: bool = False, current: bool = False) -> MagicMock:
    notice = MagicMock()
    notice.title = title
    notice.deleted_at = datetime(2026, 1, 1, tzinfo=UTC) if deleted else None
    notice.cleaner_version = DEFAULT_CLEANER_VERSION if current else "old"
    notice.structured_sections = [{"kind": "title", "text": "Existing"}] if current else []
    return notice


def test_apply_batch_preprocess_sync_skips_missing_deleted_and_current_rows() -> None:
    missing_id = uuid.uuid4()
    deleted = _notice(title="Deleted", deleted=True)
    current = _notice(title="Current", current=True)
    stale = _notice(title="  Fresh title  ")
    session = MagicMock()
    session.get.side_effect = [None, deleted, current, stale]

    apply_batch_preprocess_sync(session, [missing_id, uuid.uuid4(), uuid.uuid4(), uuid.uuid4()])

    assert session.get.call_count == 4
    assert deleted.structured_sections == []
    assert current.structured_sections == [{"kind": "title", "text": "Existing"}]
    assert stale.structured_sections == [{"kind": "title", "text": "Fresh title"}]
    assert stale.cleaner_version == DEFAULT_CLEANER_VERSION


def test_apply_batch_preprocess_sync_handles_empty_title_as_empty_sections() -> None:
    notice = _notice(title="   ")
    session = MagicMock()
    session.get.return_value = notice

    apply_batch_preprocess_sync(session, [uuid.uuid4()])

    assert notice.structured_sections == []
    assert notice.cleaner_version == DEFAULT_CLEANER_VERSION
