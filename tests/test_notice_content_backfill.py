"""본문 백필: RETURNING에 없는 행도 key_to_id 보완 후 notice_contents upsert 검증."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.domain.contracts.crawl_contracts import NoticeDraft
from app.repositories import notice_repository
from app.repositories.notice_repository import (
    _build_notice_contents_upsert_payloads,
    _fill_key_to_id_from_notices,
    _fill_key_to_id_from_notices_sync,
    _keys_with_content_but_missing,
    _sorted_notice_drafts,
    _upsert_notice_contents_bulk_from_drafts_sync,
)


def _draft(cid: uuid.UUID, eid: str, content_url: str | None = None) -> NoticeDraft:
    return NoticeDraft(
        college_id=cid,
        external_id=eid,
        title="",
        url=None,
        content_url=content_url,
    )


def test_keys_with_content_but_missing():
    """content_url 있는 draft 중 key_to_id에 없는 (college_id, external_id)만 반환."""
    cid = uuid.uuid4()
    key_to_id = {(cid, "ext-1"): uuid.uuid4()}
    drafts = [
        _draft(cid, "ext-1", "https://a/1"),
        _draft(cid, "ext-2", "https://a/2"),
        _draft(cid, "ext-3"),  # no content_url
    ]
    missing = _keys_with_content_but_missing(drafts, key_to_id)
    assert set(missing) == {(cid, "ext-2")}


def test_keys_with_content_but_missing_deduplicates_duplicate_keys() -> None:
    cid = uuid.uuid4()
    drafts = [
        _draft(cid, "ext-2", "https://a/2"),
        _draft(cid, "ext-2", "https://a/2-new"),
    ]
    missing = _keys_with_content_but_missing(drafts, {})
    assert missing == [(cid, "ext-2")]


def test_sorted_notice_drafts_deduplicates_by_key_last_wins() -> None:
    cid = uuid.uuid4()
    older = NoticeDraft(
        college_id=cid,
        external_id="ext-1",
        title="old",
        url="https://example.com/old",
        content_url="https://content/old",
        content_hash="old-hash",
    )
    newer = NoticeDraft(
        college_id=cid,
        external_id="ext-1",
        title="new",
        url="https://example.com/new",
        content_url=None,
        content_hash="new-hash",
    )
    other = _draft(cid, "ext-2", "https://content/other")

    out = _sorted_notice_drafts([other, older, newer])

    assert [d.external_id for d in out] == ["ext-1", "ext-2"]
    assert out[0] is newer


def test_build_notice_contents_upsert_payloads_deduplicates_by_notice_id_last_wins() -> None:
    cid = uuid.uuid4()
    nid1 = uuid.uuid4()
    nid2 = uuid.uuid4()
    drafts = [
        _draft(cid, "ext-1", "https://content/old"),
        _draft(cid, "ext-2", "https://content/2"),
        _draft(cid, "ext-1", "https://content/new"),
    ]

    out = _build_notice_contents_upsert_payloads(
        drafts,
        {
            (cid, "ext-1"): nid1,
            (cid, "ext-2"): nid2,
        },
    )

    assert {row["notice_id"]: row["content_url"] for row in out} == {
        nid1: "https://content/new",
        nid2: "https://content/2",
    }
    assert [row["notice_id"] for row in out] == sorted([nid1, nid2])


def test_fill_key_to_id_from_notices_sync_adds_missing_mapping():
    """동일 content_hash로 RETURNING에 없던 (cid, eid)가 DB에 있으면 key_to_id에 채워짐."""
    from sqlalchemy.orm import Session

    cid = uuid.uuid4()
    nid = uuid.uuid4()
    key_to_id = {}
    drafts = [_draft(cid, "ext-1", "https://a/1")]
    mock_session = MagicMock(spec=Session)
    mock_result = MagicMock()
    mock_result.all.return_value = [(nid, cid, "ext-1")]
    mock_session.execute.return_value = mock_result

    _fill_key_to_id_from_notices_sync(mock_session, drafts, key_to_id)
    assert key_to_id == {(cid, "ext-1"): nid}


def test_fill_key_to_id_from_notices_sync_uses_builder(monkeypatch):
    """_fill_key_to_id_from_notices_sync가 _build_missing_notice_stmt를 호출하고 그 반환 statement로 execute한다."""
    from sqlalchemy.orm import Session

    cid = uuid.uuid4()
    nid = uuid.uuid4()
    key_to_id = {}
    drafts = [_draft(cid, "ext-1", "https://a/1")]
    builder_calls = []
    original_builder = notice_repository._build_missing_notice_stmt

    def _spy_builder(missing):
        stmt = original_builder(missing)
        builder_calls.append((list(missing), stmt))
        return stmt

    monkeypatch.setattr(notice_repository, "_build_missing_notice_stmt", _spy_builder)
    mock_session = MagicMock(spec=Session)
    mock_result = MagicMock()
    mock_result.all.return_value = [(nid, cid, "ext-1")]
    mock_session.execute.return_value = mock_result

    _fill_key_to_id_from_notices_sync(mock_session, drafts, key_to_id)

    assert len(builder_calls) == 1
    assert builder_calls[0][0] == [(cid, "ext-1")]
    assert mock_session.execute.call_count == 1
    assert mock_session.execute.call_args[0][0] is builder_calls[0][1]


@pytest.mark.asyncio
async def test_fill_key_to_id_from_notices_async_uses_builder(monkeypatch):
    """_fill_key_to_id_from_notices가 _build_missing_notice_stmt를 호출하고 그 반환 statement로 execute한다."""
    from sqlalchemy.ext.asyncio import AsyncSession

    cid = uuid.uuid4()
    nid = uuid.uuid4()
    key_to_id = {}
    drafts = [_draft(cid, "ext-1", "https://a/1")]
    builder_calls = []
    original_builder = notice_repository._build_missing_notice_stmt

    def _spy_builder(missing):
        stmt = original_builder(missing)
        builder_calls.append((list(missing), stmt))
        return stmt

    monkeypatch.setattr(notice_repository, "_build_missing_notice_stmt", _spy_builder)
    mock_session = MagicMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.all.return_value = [(nid, cid, "ext-1")]
    mock_session.execute = AsyncMock(return_value=mock_result)

    await _fill_key_to_id_from_notices(mock_session, drafts, key_to_id)

    assert len(builder_calls) == 1
    assert builder_calls[0][0] == [(cid, "ext-1")]
    assert mock_session.execute.await_count == 1
    assert mock_session.execute.await_args[0][0] is builder_calls[0][1]


def test_upsert_notice_contents_bulk_from_drafts_sync_batches_large_payloads(monkeypatch) -> None:
    from sqlalchemy.orm import Session

    cid = uuid.uuid4()
    drafts = [
        _draft(cid, "ext-1", "https://content/1"),
        _draft(cid, "ext-2", "https://content/2"),
        _draft(cid, "ext-3", "https://content/3"),
    ]
    key_to_id = {
        (cid, "ext-1"): uuid.uuid4(),
        (cid, "ext-2"): uuid.uuid4(),
        (cid, "ext-3"): uuid.uuid4(),
    }
    session = MagicMock(spec=Session)

    monkeypatch.setattr(notice_repository, "BULK_UPSERT_BATCH_SIZE", 2)

    _upsert_notice_contents_bulk_from_drafts_sync(session, drafts, key_to_id)

    assert session.execute.call_count == 2
    session.flush.assert_called_once()
