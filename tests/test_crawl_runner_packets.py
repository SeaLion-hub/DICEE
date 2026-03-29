"""Runner 패킷 매핑."""

import uuid
from datetime import UTC, datetime

from app.domain.contracts.crawl_contracts import NoticeDraft
from app.services.crawl.crawl_runner import (
    iter_packets_from_drafts,
    list_fetch_failure_packet,
    notice_draft_to_runner_document,
)


def test_notice_draft_to_runner_document():
    d = NoticeDraft(
        college_id=uuid.uuid4(),
        external_id="e",
        title="x",
        url="u",
        content_url=None,
        images=None,
        attachments=[],
        content_hash="h",
        published_at=datetime.now(UTC),
    )
    p = notice_draft_to_runner_document(d)
    assert p.kind == "notice_document"
    assert p.external_id == "e"


def test_iter_packets_from_drafts():
    cid = uuid.uuid4()
    d = NoticeDraft(
        college_id=cid,
        external_id="1",
        title="t",
        url=None,
        content_url=None,
        images=None,
        attachments=[],
        content_hash="",
        published_at=None,
    )
    out = list(iter_packets_from_drafts([d]))
    assert len(out) == 1
    assert out[0].college_id == cid


def test_list_fetch_failure_packet_kind():
    f = list_fetch_failure_packet("boom", event_code="CRAWL_LIST_FETCH_FAILED")
    assert f.kind == "crawl_failure"
    assert f.phase == "list"
