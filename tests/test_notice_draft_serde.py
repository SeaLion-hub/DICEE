"""NoticeDraft JSON 직렬화 라운드트립."""

import uuid
from datetime import UTC, datetime

from app.domain.contracts.crawl_contracts import NoticeDraft
from app.domain.contracts.notice_draft_serde import notice_draft_from_payload, notice_draft_to_payload


def test_notice_draft_serde_roundtrip():
    d = NoticeDraft(
        college_id=uuid.uuid4(),
        external_id="ext-1",
        title="T",
        url="https://example.com/n/1",
        content_url=None,
        images=None,
        attachments=[{"name": "a.pdf"}],
        content_hash="abc",
        published_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )
    p = notice_draft_to_payload(d)
    d2 = notice_draft_from_payload(p)
    assert d2.college_id == d.college_id
    assert d2.external_id == d.external_id
    assert d2.title == d.title
    assert d2.published_at == d.published_at
