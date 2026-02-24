"""본문 백필: RETURNING에 없는 행도 key_to_id 보완 후 notice_contents upsert 검증."""

import uuid
from unittest.mock import MagicMock

import pytest

from app.repositories.notice_repository import (
    _fill_key_to_id_from_notices_sync,
    _keys_with_content_but_missing,
)


def test_keys_with_content_but_missing():
    """content_url 있는 payload 중 key_to_id에 없는 (college_id, external_id)만 반환."""
    cid = uuid.uuid4()
    key_to_id = {(cid, "ext-1"): uuid.uuid4()}
    payloads = [
        {"college_id": cid, "external_id": "ext-1", "content_url": "https://a/1"},
        {"college_id": cid, "external_id": "ext-2", "content_url": "https://a/2"},
        {"college_id": cid, "external_id": "ext-3"},
    ]
    missing = _keys_with_content_but_missing(payloads, key_to_id)
    assert set(missing) == {(cid, "ext-2")}


def test_fill_key_to_id_from_notices_sync_adds_missing_mapping():
    """동일 content_hash로 RETURNING에 없던 (cid, eid)가 DB에 있으면 key_to_id에 채워짐."""
    from sqlalchemy.orm import Session

    cid = uuid.uuid4()
    nid = uuid.uuid4()
    key_to_id = {}
    payloads = [
        {"college_id": cid, "external_id": "ext-1", "content_url": "https://a/1"},
    ]
    mock_session = MagicMock(spec=Session)
    mock_result = MagicMock()
    mock_result.all.return_value = [(nid, cid, "ext-1")]
    mock_session.execute.return_value = mock_result

    _fill_key_to_id_from_notices_sync(mock_session, payloads, key_to_id)
    assert key_to_id == {(cid, "ext-1"): nid}