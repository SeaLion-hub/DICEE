"""HTML 없이도 제목 기반 섹션 스냅샷을 남긴다. 본문 URL 기반 정제는 후속 확장."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.notice import Notice

DEFAULT_CLEANER_VERSION = "v1"


def sectionize_from_title_body(*, title: str, body_text: str = "") -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    t = (title or "").strip()
    if t:
        sections.append({"kind": "title", "text": t})
    b = (body_text or "").strip()
    if b:
        sections.append({"kind": "body", "text": b[:50_000]})
    return sections


def apply_batch_preprocess_sync(session: Session, notice_ids: list[uuid.UUID]) -> None:
    """upsert 직후 동일 세션에서 cleaner_version·structured_sections 갱신."""
    ver = DEFAULT_CLEANER_VERSION
    for nid in notice_ids:
        n = session.get(Notice, nid)
        if n is None or n.deleted_at is not None:
            continue
        if n.cleaner_version == ver and n.structured_sections:
            continue
        n.structured_sections = sectionize_from_title_body(title=n.title or "", body_text="")
        n.cleaner_version = ver
