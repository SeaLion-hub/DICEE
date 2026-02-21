"""Notice Repository. DB 쿼리만 수행. 크롤 결과 upsert.

목록 조회(Pagination) 시 raw_html·images·attachments는 반드시 지연 로딩.
쓰려면 select(Notice).options(*NOTICE_LIST_DEFER_OPTIONS) 형태로 사용.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, defer

from app.models.notice import Notice

# 목록 조회 시 Heavy column 지연 로딩 (메모리·대역폭 방지). 5단계 목록 API에서 필수.
NOTICE_LIST_DEFER_OPTIONS = (
    defer(Notice.raw_html),
    defer(Notice.images),
    defer(Notice.attachments),
)


def get_by_id_sync(session: Session, notice_id: int) -> Notice | None:
    """notice_id로 1건 조회 (동기, 워커용). 4단계 AI 태스크 멱등 처리용."""
    result = session.execute(select(Notice).where(Notice.id == notice_id).limit(1))
    return result.scalars().one_or_none()


def get_by_college_external_sync(
    session: Session,
    college_id: int,
    external_id: str,
) -> Notice | None:
    """college_id + external_id로 기존 Notice 조회 (동기, 워커용). 3→4 content_hash 변경 감지용."""
    stmt = (
        select(Notice)
        .where(
            Notice.college_id == college_id,
            Notice.external_id == external_id,
        )
        .limit(1)
    )
    result = session.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_notice(
    session: AsyncSession,
    college_id: int,
    external_id: str,
    title: str,
    url: str | None,
    raw_html: str | None,
    images: list[dict[str, Any]] | None,
    attachments: list[dict[str, Any]] | None,
    content_hash: str | None,
    published_at: datetime | None = None,
) -> Notice:
    """
    college_id + external_id 기준으로 insert or update.
    PostgreSQL on_conflict_do_update 사용.
    """
    values = {
        "college_id": college_id,
        "external_id": external_id,
        "title": title,
        "url": url,
        "raw_html": raw_html,
        "images": images,
        "attachments": attachments,
        "content_hash": content_hash,
        "published_at": published_at,
    }
    stmt = (
        insert(Notice)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_notice_college_external",
            set_={
                "title": title,
                "url": url,
                "raw_html": raw_html,
                "images": images,
                "attachments": attachments,
                "content_hash": content_hash,
                "published_at": published_at,
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(Notice)
    )
    result = await session.execute(stmt)
    row = result.scalar_one()
    await session.flush()
    await session.refresh(row)
    return row


def upsert_notice_sync(
    session: Session,
    college_id: int,
    external_id: str,
    title: str,
    url: str | None,
    raw_html: str | None,
    images: list[dict[str, Any]] | None,
    attachments: list[dict[str, Any]] | None,
    content_hash: str | None,
    published_at: datetime | None = None,
) -> Notice:
    """
    college_id + external_id 기준으로 insert or update (동기, 워커용).
    PostgreSQL on_conflict_do_update 사용.
    """
    values = {
        "college_id": college_id,
        "external_id": external_id,
        "title": title,
        "url": url,
        "raw_html": raw_html,
        "images": images,
        "attachments": attachments,
        "content_hash": content_hash,
        "published_at": published_at,
    }
    stmt = (
        insert(Notice)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_notice_college_external",
            set_={
                "title": title,
                "url": url,
                "raw_html": raw_html,
                "images": images,
                "attachments": attachments,
                "content_hash": content_hash,
                "published_at": published_at,
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(Notice)
    )
    result = session.execute(stmt)
    row = result.scalar_one()
    session.flush()
    session.refresh(row)
    return row


def _notice_upsert_set_excluded(stmt: Any) -> dict:
    """Bulk upsert set_ dict using excluded. stmt = insert(Notice).values(rows)."""
    return {
        "title": stmt.excluded.title,
        "url": stmt.excluded.url,
        "raw_html": stmt.excluded.raw_html,
        "images": stmt.excluded.images,
        "attachments": stmt.excluded.attachments,
        "content_hash": stmt.excluded.content_hash,
        "published_at": stmt.excluded.published_at,
        "updated_at": datetime.now(UTC),
    }


async def upsert_notices_bulk(
    session: AsyncSession,
    notices: list[dict[str, Any]],
) -> list[int]:
    """
    여러 공지를 한 트랜잭션으로 bulk upsert.
    content_hash가 실제로 변한 행만 업데이트하고, RETURNING id로 신규/변경 공지 ID만 반환 (AI 큐 대상).
    """
    if not notices:
        return []
    base = insert(Notice).values(notices)
    stmt = base.on_conflict_do_update(
        constraint="uq_notice_college_external",
        set_=_notice_upsert_set_excluded(base),
        where=Notice.content_hash.is_distinct_from(base.excluded.content_hash),
    ).returning(Notice.id)
    result = await session.execute(stmt)
    ids = list(result.scalars().all())
    await session.flush()
    return ids


def upsert_notices_bulk_sync(
    session: Session,
    notices: list[dict[str, Any]],
) -> list[int]:
    """
    동기 bulk upsert (Celery 워커용).
    content_hash가 실제로 변한 행만 업데이트, RETURNING id로 신규/변경 공지 ID만 반환.
    """
    if not notices:
        return []
    base = insert(Notice).values(notices)
    stmt = base.on_conflict_do_update(
        constraint="uq_notice_college_external",
        set_=_notice_upsert_set_excluded(base),
        where=Notice.content_hash.is_distinct_from(base.excluded.content_hash),
    ).returning(Notice.id)
    result = session.execute(stmt)
    ids = list(result.scalars().all())
    session.flush()
    return ids
