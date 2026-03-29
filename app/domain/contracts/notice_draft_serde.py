"""NoticeDraft JSONB 직렬화 (ingestion_batches.drafts_payload)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.domain.contracts.crawl_contracts import NoticeDraft


def notice_draft_to_payload(d: NoticeDraft) -> dict[str, Any]:
    return {
        "college_id": str(d.college_id),
        "external_id": d.external_id,
        "title": d.title,
        "url": d.url,
        "content_url": d.content_url,
        "images": d.images,
        "attachments": list(d.attachments or []),
        "content_hash": d.content_hash,
        "published_at": d.published_at.isoformat() if d.published_at else None,
    }


def notice_draft_from_payload(raw: dict[str, Any]) -> NoticeDraft:
    pub = raw.get("published_at")
    published_at = datetime.fromisoformat(pub) if isinstance(pub, str) and pub.strip() else None
    return NoticeDraft(
        college_id=uuid.UUID(str(raw["college_id"])),
        external_id=str(raw["external_id"]),
        title=str(raw.get("title") or ""),
        url=raw.get("url"),
        content_url=raw.get("content_url"),
        images=raw.get("images"),
        attachments=list(raw.get("attachments") or []),
        content_hash=str(raw.get("content_hash") or ""),
        published_at=published_at,
    )
