"""CollegeSource 동기 조회·보장."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG
from app.models.college import College
from app.models.college_source import CollegeSource


def get_primary_college_source_sync(session: Session, college_id: uuid.UUID) -> CollegeSource | None:
    return session.execute(
        select(CollegeSource)
        .where(
            CollegeSource.college_id == college_id,
            CollegeSource.is_primary.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()


def ensure_primary_college_source_sync(session: Session, college: College) -> CollegeSource:
    """primary CollegeSource가 없으면 레지스트리 URL·모듈명으로 1건 생성."""
    existing = get_primary_college_source_sync(session, college.id)
    if existing is not None:
        return existing
    code = (college.external_id or "").strip()
    mod = COLLEGE_CODE_TO_MODULE.get(code)
    if not mod:
        raise ValueError(f"No crawler module for college external_id: {code!r}")
    cfg = CRAWLER_CONFIG.get(mod)
    if not cfg or not (cfg.get("url") or "").strip():
        raise ValueError(f"No crawler url for module: {mod!r}")
    now = datetime.now(UTC)
    row = CollegeSource(
        college_id=college.id,
        list_url=str(cfg["url"]),
        crawler_engine_key=mod,
        connector_config={},
        is_primary=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row
