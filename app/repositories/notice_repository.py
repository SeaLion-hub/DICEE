"""Notice Repository. DB 쿼리만 수행. 크롤 결과 upsert.

목록 조회(Pagination) 시 images·attachments는 반드시 지연 로딩.
본문은 notice_contents.content_url로 S3 등에 분리 저장.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, defer, selectinload

from app.domain.contracts.crawl_contracts import NoticeDraft
from app.models.notice import Notice
from app.models.notice_content import NoticeContent

# 목록 조회 시 Heavy column 지연 로딩 (메모리·대역폭 방지). 5단계 목록 API에서 필수.
NOTICE_LIST_DEFER_OPTIONS = (
    defer(Notice.images),
    defer(Notice.attachments),
)


async def list_notices_paginated(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    college_id: uuid.UUID | None = None,
    load_college: bool = True,
) -> list[Notice]:
    """
    공지 목록 페이지네이션 조회. N+1 방지: NOTICE_LIST_DEFER_OPTIONS + 필요 시 selectinload(Notice.college).
    5단계 목록 API에서 사용. deleted_at IS NULL만 반환.
    """
    stmt = (
        select(Notice)
        .where(Notice.deleted_at.is_(None))
        .options(*NOTICE_LIST_DEFER_OPTIONS)
        .order_by(Notice.published_at.desc().nulls_last(), Notice.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if load_college:
        stmt = stmt.options(selectinload(Notice.college))
    if college_id is not None:
        stmt = stmt.where(Notice.college_id == college_id)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_notice_by_id_with_relations(
    session: AsyncSession,
    notice_id: uuid.UUID,
) -> Notice | None:
    """
    공지 1건 상세 조회. college, notice_content 관계를 selectinload로 한 번에 로딩하여 N+1 방지.
    5단계 상세 API에서 사용.
    """
    stmt = (
        select(Notice)
        .where(Notice.id == notice_id, Notice.deleted_at.is_(None))
        .options(
            selectinload(Notice.college),
            selectinload(Notice.notice_content),
        )
    )
    result = await session.execute(stmt)
    return result.scalars().unique().one_or_none()


def get_by_id_sync(session: Session, notice_id: uuid.UUID) -> Notice | None:
    """notice_id로 1건 조회 (동기, 워커용)."""
    result = session.execute(select(Notice).where(Notice.id == notice_id).limit(1))
    return result.scalars().one_or_none()


def get_notice_for_ai_sync(session: Session, notice_id: uuid.UUID) -> Notice | None:
    """
    AI 처리 대상 1건 선점. ai_status='pending'인 행만 FOR UPDATE SKIP LOCKED로 잡고
    ai_status='processing'으로 갱신 후 반환. 동시 워커 중복 처리 방지.
    """
    stmt = select(Notice).where(Notice.id == notice_id, Notice.ai_status == "pending").with_for_update(skip_locked=True)
    result = session.execute(stmt)
    notice = result.scalar_one_or_none()
    if notice is None:
        return None
    notice.ai_status = "processing"
    session.flush()
    return notice


def update_ai_result_sync(
    session: Session,
    notice_id: uuid.UUID,
    ai_extracted_json: dict[str, Any],
) -> None:
    """AI 처리 완료 시 ai_status='done', ai_extracted_json 저장 (동기, 워커용)."""
    stmt = update(Notice).where(Notice.id == notice_id).values(ai_status="done", ai_extracted_json=ai_extracted_json)
    session.execute(stmt)
    session.flush()


def get_by_college_external_sync(
    session: Session,
    college_id: uuid.UUID,
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


def update_notice_content_url_sync(
    session: Session,
    college_id: uuid.UUID,
    external_id: str,
    content_url: str,
) -> bool:
    """
    (college_id, external_id)에 해당하는 Notice의 notice_contents에 content_url을 upsert.
    스풀 드레인에서 재업로드 성공 후 DB 반영용. Notice가 없으면 False.
    """
    notice = get_by_college_external_sync(session, college_id, external_id)
    if notice is None:
        return False
    ins = insert(NoticeContent).values(
        notice_id=notice.id,
        content_url=content_url,
    )
    stmt = ins.on_conflict_do_update(
        index_elements=["notice_id"],
        set_={"content_url": ins.excluded.content_url, "updated_at": datetime.now(UTC)},
    )
    session.execute(stmt)
    session.flush()
    return True


def _draft_to_notice_dict(draft: NoticeDraft) -> dict[str, Any]:
    """NoticeDraft → DB/내부용 dict. SQLAlchemy가 기대하는 형식(datetime, UUID 그대로) 유지."""
    return {
        "college_id": draft.college_id,
        "external_id": draft.external_id,
        "title": draft.title,
        "url": draft.url,
        "content_url": draft.content_url,
        "images": draft.images,
        "attachments": draft.attachments,
        "content_hash": draft.content_hash,
        "published_at": draft.published_at,
    }


def _notice_values_no_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Notice 테이블용 dict (raw_html·content_url 제외)."""
    out = {k: v for k, v in payload.items() if k not in ("raw_html", "content_url")}
    return out


def _notice_upsert_set_excluded(stmt: Any) -> dict:
    """Bulk upsert set_ dict using excluded. content 변경 시 AI 재처리를 위해 ai_status='pending'."""
    return {
        "title": stmt.excluded.title,
        "url": stmt.excluded.url,
        "images": stmt.excluded.images,
        "attachments": stmt.excluded.attachments,
        "content_hash": stmt.excluded.content_hash,
        "published_at": stmt.excluded.published_at,
        "ai_status": "pending",
        "updated_at": datetime.now(UTC),
    }


def _keys_with_content_but_missing(
    payloads: list[dict[str, Any]],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> list[tuple[uuid.UUID, str]]:
    """content_url이 있는 payload 중 key_to_id에 없는 (college_id, external_id) 목록."""
    missing: list[tuple[uuid.UUID, str]] = []
    for p in payloads:
        if not p.get("content_url"):
            continue
        cid, eid = p.get("college_id"), p.get("external_id")
        if cid is None or eid is None:
            continue
        k = (cid, eid)
        if k not in key_to_id:
            missing.append(k)
    return missing


def _build_missing_notice_stmt(
    missing: list[tuple[uuid.UUID, str]],
):
    """missing 기준 Notice id/college_id/external_id 조회용 select statement. len(missing) >= 1 전제."""
    if len(missing) == 1:
        (cid, eid) = missing[0]
        return select(Notice.id, Notice.college_id, Notice.external_id).where(
            Notice.college_id == cid, Notice.external_id == eid
        )
    return select(Notice.id, Notice.college_id, Notice.external_id).where(
        tuple_(Notice.college_id, Notice.external_id).in_(missing)
    )


def _build_bulk_upsert_stmt(notices: list[dict[str, Any]]) -> tuple[Any, list[dict[str, Any]]]:
    """
    Bulk upsert용 Insert statement와 정렬된 notices를 반환. 데드락 방지를 위해
    (college_id, external_id) 기준 오름차순 정렬. sync/async 실행부에서 공통 사용.
    """
    # [핵심 리팩토링: 데드락 방지]
    # 병렬 Celery 워커들이 무작위 순서로 행(Row) 잠금을 획득하여 데드락이 발생하는 것을 막기 위해,
    # 복합 유니크 키(college_id, external_id)를 기준으로 항상 오름차순 정렬합니다.
    sorted_notices = sorted(
        notices,
        key=lambda x: (str(x.get("college_id", "")), str(x.get("external_id", ""))),
    )
    notice_rows = [_notice_values_no_content(p) for p in sorted_notices]
    base = insert(Notice).values(notice_rows)
    stmt = base.on_conflict_do_update(
        index_elements=["college_id", "external_id"],
        index_where=Notice.deleted_at.is_(None),
        set_=_notice_upsert_set_excluded(base),
        where=Notice.content_hash.is_distinct_from(base.excluded.content_hash),
    ).returning(Notice.id, Notice.college_id, Notice.external_id)
    return stmt, sorted_notices


def _build_notice_contents_upsert_payloads(
    payloads: list[dict[str, Any]],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> list[dict[str, Any]]:
    """payloads와 key_to_id로 notice_contents upsert용 to_insert 리스트 구성. sync/async 공통."""
    to_insert: list[dict[str, Any]] = []
    for p in payloads:
        content_url = p.get("content_url")
        if not content_url:
            continue
        cid = p.get("college_id")
        eid = p.get("external_id")
        if cid is None or eid is None:
            continue
        nid = key_to_id.get((cid, eid))
        if nid is None:
            continue
        to_insert.append({"notice_id": nid, "content_url": content_url})
    return to_insert


async def _fill_key_to_id_from_notices(
    session: AsyncSession,
    payloads: list[dict[str, Any]],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """RETURNING에 없는(동일 content_hash) 행의 notice_id를 조회해 key_to_id 보완. 본문 백필 가능."""
    missing = _keys_with_content_but_missing(payloads, key_to_id)
    if not missing:
        return
    stmt = _build_missing_notice_stmt(missing)
    result = await session.execute(stmt)
    for row in result.all():
        nid, cid, eid = row[0], row[1], row[2]
        key_to_id[(cid, eid)] = nid


def _fill_key_to_id_from_notices_sync(
    session: Session,
    payloads: list[dict[str, Any]],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """동기: RETURNING에 없는 행의 notice_id 조회해 key_to_id 보완."""
    missing = _keys_with_content_but_missing(payloads, key_to_id)
    if not missing:
        return
    stmt = _build_missing_notice_stmt(missing)
    result = session.execute(stmt)
    for row in result.all():
        nid, cid, eid = row[0], row[1], row[2]
        key_to_id[(cid, eid)] = nid


async def upsert_notices_bulk(
    session: AsyncSession,
    notices: Sequence[NoticeDraft],
) -> list[uuid.UUID]:
    """
    여러 공지를 한 트랜잭션으로 bulk upsert.
    payload에 content_url이 있으면 notice_contents도 upsert.
    content_hash가 실제로 변한 행만 업데이트하고, RETURNING id로 신규/변경 공지 ID만 반환 (AI 큐 대상).
    """
    if not notices:
        return []
    notices_dicts = [_draft_to_notice_dict(d) for d in notices]
    stmt, sorted_notices = _build_bulk_upsert_stmt(notices_dicts)
    result = await session.execute(stmt)
    rows = result.all()
    await session.flush()
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    ids: list[uuid.UUID] = []
    for row in rows:
        nid, cid, eid = row[0], row[1], row[2]
        key_to_id[(cid, eid)] = nid
        ids.append(nid)
    # RETURNING에 없는(동일 content_hash) 행도 notice_id 조회해 본문 백필 가능하도록 보완.
    await _fill_key_to_id_from_notices(session, sorted_notices, key_to_id)
    await _upsert_notice_contents_bulk_from_payloads(session, sorted_notices, key_to_id)
    return ids


def upsert_notices_bulk_sync(
    session: Session,
    notices: Sequence[NoticeDraft],
) -> list[uuid.UUID]:
    """
    동기 bulk upsert (Celery 워커용).
    payload에 content_url이 있으면 notice_contents도 upsert.
    content_hash가 실제로 변한 행만 업데이트, RETURNING id로 신규/변경 공지 ID만 반환.
    """
    if not notices:
        return []
    notices_dicts = [_draft_to_notice_dict(d) for d in notices]
    stmt, sorted_notices = _build_bulk_upsert_stmt(notices_dicts)
    result = session.execute(stmt)
    rows = result.all()
    session.flush()
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    ids: list[uuid.UUID] = []
    for row in rows:
        nid, cid, eid = row[0], row[1], row[2]
        key_to_id[(cid, eid)] = nid
        ids.append(nid)
    _fill_key_to_id_from_notices_sync(session, sorted_notices, key_to_id)
    _upsert_notice_contents_bulk_from_payloads_sync(session, sorted_notices, key_to_id)
    return ids


def _upsert_notice_contents_bulk_from_payloads_sync(
    session: Session,
    payloads: list[dict[str, Any]],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """payloads와 key_to_id로 notice_contents bulk upsert (동기)."""
    to_insert = _build_notice_contents_upsert_payloads(payloads, key_to_id)
    if not to_insert:
        return
    ins = insert(NoticeContent).values(to_insert)
    stmt = ins.on_conflict_do_update(
        index_elements=["notice_id"],
        set_={"content_url": ins.excluded.content_url, "updated_at": datetime.now(UTC)},
    )
    session.execute(stmt)
    session.flush()


async def _upsert_notice_contents_bulk_from_payloads(
    session: AsyncSession,
    payloads: list[dict[str, Any]],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """payloads와 key_to_id로 notice_contents bulk upsert (비동기)."""
    to_insert = _build_notice_contents_upsert_payloads(payloads, key_to_id)
    if not to_insert:
        return
    ins = insert(NoticeContent).values(to_insert)
    stmt = ins.on_conflict_do_update(
        index_elements=["notice_id"],
        set_={"content_url": ins.excluded.content_url, "updated_at": datetime.now(UTC)},
    )
    await session.execute(stmt)
    await session.flush()
