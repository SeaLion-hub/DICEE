"""Notice Repository. DB 쿼리만 수행. 크롤 결과 upsert.

목록 조회(Pagination) 시 images·attachments는 반드시 지연 로딩.
본문은 notice_contents.content_url로 S3 등에 분리 저장.
"""

import base64
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, defer, selectinload

from app.constants.embeddings import EMBEDDING_DIM
from app.core.database import AsyncSessionLike
from app.domain.contracts.crawl_contracts import NoticeDraft
from app.models.college import College
from app.models.notice import Notice
from app.models.notice_content import NoticeContent
from app.models.notice_taxonomy_mapping import NoticeTaxonomyMapping

# 단일 execute당 최대 행 수. 락/WAL·데드락 리스크 완화용.
BULK_UPSERT_BATCH_SIZE = 500

# 목록 조회 시 Heavy column 지연 로딩 (메모리·대역폭 방지). 5단계 목록 API에서 필수.
NOTICE_LIST_DEFER_OPTIONS = (
    defer(Notice.images),
    defer(Notice.attachments),
)


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, datetime | None, uuid.UUID | None] | None:
    """cursor 문자열을 (published_at, created_at, id)로 복원. 실패 시 None."""
    if not cursor or not cursor.strip():
        return None
    try:
        raw = base64.b64decode(cursor.encode()).decode()
        parts = raw.split("|")
        if len(parts) != 3:
            return None
        pub_s, created_s, id_s = parts[0], parts[1], parts[2]
        pub = datetime.fromisoformat(pub_s) if pub_s else None
        created = datetime.fromisoformat(created_s) if created_s else None
        nid = uuid.UUID(id_s) if id_s else None
        return (pub, created, nid)
    except (ValueError, AttributeError):
        return None


def _encode_cursor(published_at: datetime | None, created_at: datetime | None, notice_id: uuid.UUID) -> str:
    """다음 페이지용 cursor 인코딩. (published_at, created_at, id) -> base64."""
    pub_s = published_at.isoformat() if published_at else ""
    created_s = created_at.isoformat() if created_at else ""
    return base64.b64encode(f"{pub_s}|{created_s}|{notice_id}".encode()).decode()


def encode_notice_list_cursor(
    published_at: datetime | None,
    created_at: datetime | None,
    notice_id: uuid.UUID,
) -> str:
    """매칭 피드 등에서 마지막 반환 공지 기준 다음 키셋 커서."""
    return _encode_cursor(published_at, created_at, notice_id)


async def list_notices_paginated(
    session: AsyncSessionLike,
    *,
    limit: int = 20,
    offset: int = 0,
    cursor: str | None = None,
    college_id: uuid.UUID | None = None,
    load_college: bool = True,
    load_taxonomy_mappings: bool = False,
) -> tuple[list[Notice], str | None]:
    """
    공지 목록 페이지네이션 조회. N+1 방지: NOTICE_LIST_DEFER_OPTIONS + selectinload(Notice.college).
    응답에 taxonomy_mappings가 필요하면 load_taxonomy_mappings=True로 selectinload(Notice.taxonomy_mappings) 적용.

    cursor가 있으면 keyset(이전 페이지 마지막 행 기준)으로 다음 페이지를 가져온다.
    cursor가 없으면 offset으로 윈도우를 잡되, 내부적으로 limit+1로 조회해 더 있으면 next_cursor를 채운다.
    다음 요청은 cursor를 넣는 것을 권장한다(정렬 일관성). 반환 (rows, next_cursor).
    deleted_at IS NULL만 반환.
    """
    order = (
        Notice.published_at.desc().nulls_last(),
        Notice.created_at.desc(),
        Notice.id.desc(),
    )
    decoded = _decode_cursor(cursor) if cursor else None
    keyset_cond = None
    if decoded is not None:
        pub, created, nid = decoded
        if pub is not None and nid is not None:
            if created is not None:
                keyset_cond = or_(
                    Notice.published_at < pub,
                    and_(
                        Notice.published_at == pub,
                        Notice.created_at < created,
                    ),
                    and_(
                        Notice.published_at == pub,
                        Notice.created_at == created,
                        Notice.id < nid,
                    ),
                )
            else:
                keyset_cond = or_(
                    Notice.published_at < pub,
                    and_(Notice.published_at == pub, Notice.id < nid),
                )
        elif pub is None and nid is not None:
            keyset_cond = Notice.published_at.isnot(None)

    if keyset_cond is not None:
        stmt = (
            select(Notice)
            .where(Notice.deleted_at.is_(None), keyset_cond)
            .options(*NOTICE_LIST_DEFER_OPTIONS)
            .order_by(*order)
            .limit(limit + 1)
        )
    else:
        stmt = (
            select(Notice)
            .where(Notice.deleted_at.is_(None))
            .options(*NOTICE_LIST_DEFER_OPTIONS)
            .order_by(*order)
            .limit(limit + 1)
            .offset(offset)
        )

    if load_college:
        stmt = stmt.options(selectinload(Notice.college))
    if load_taxonomy_mappings:
        stmt = stmt.options(selectinload(Notice.taxonomy_mappings))
    if college_id is not None:
        stmt = stmt.where(Notice.college_id == college_id)

    result = await session.execute(stmt)
    rows = list(result.scalars().unique().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.published_at, last.created_at, last.id)

    return (rows, next_cursor)


async def get_notice_by_id_with_relations(
    session: AsyncSessionLike,
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


async def list_recent_notices_for_college_preview(
    session: AsyncSession,
    *,
    college_external_id: str,
    limit: int = 30,
) -> list[Notice]:
    """
    단과대 external_id 기준 최근 공지 조회(미리보기용).
    이미지/첨부/AI 결과/taxonomy를 함께 로드해 임시 검수 페이지에서 바로 사용한다.
    """
    stmt = (
        select(Notice)
        .join(Notice.college)
        .where(
            College.external_id == college_external_id,
            Notice.deleted_at.is_(None),
        )
        .options(
            selectinload(Notice.college),
            selectinload(Notice.notice_content),
        )
        .order_by(
            Notice.published_at.desc().nulls_last(),
            Notice.created_at.desc(),
            Notice.id.desc(),
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def search_notices_by_embedding(
    session: AsyncSessionLike,
    *,
    college_id: uuid.UUID,
    published_from: datetime,
    published_to: datetime,
    query_embedding: Sequence[float],
    limit: int = 20,
) -> list[Notice]:
    """
    단과대·게시 기간으로 좁힌 뒤 query_embedding과의 코사인 거리 오름차순으로 공지를 반환한다.
    embedding이 NULL인 행은 제외한다. deleted_at IS NULL만 포함.
    """
    if len(query_embedding) != EMBEDDING_DIM:
        raise ValueError(f"embedding dim must be {EMBEDDING_DIM}")
    q = list(query_embedding)
    distance = Notice.embedding.cosine_distance(q)
    stmt = (
        select(Notice)
        .where(
            Notice.college_id == college_id,
            Notice.published_at >= published_from,
            Notice.published_at < published_to,
            Notice.embedding.is_not(None),
            Notice.deleted_at.is_(None),
        )
        .options(
            *NOTICE_LIST_DEFER_OPTIONS,
            selectinload(Notice.college),
        )
        .order_by(distance.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


def update_notice_embedding_sync(session: Session, notice_id: uuid.UUID, embedding: Sequence[float]) -> None:
    """공지 embedding 컬럼 갱신 (동기, Celery·백필용)."""
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"embedding dim must be {EMBEDDING_DIM}")
    stmt = update(Notice).where(Notice.id == notice_id).values(embedding=list(embedding))
    session.execute(stmt)
    session.flush()


def get_by_id_sync(session: Session, notice_id: uuid.UUID) -> Notice | None:
    """notice_id로 1건 조회 (동기, 워커용)."""
    result = session.execute(select(Notice).where(Notice.id == notice_id).limit(1))
    return result.scalars().one_or_none()


def get_notice_for_ai_sync(session: Session, notice_id: uuid.UUID) -> Notice | None:
    """
    AI 처리 대상 1건 선점. ai_status='pending'인 행만 FOR UPDATE SKIP LOCKED로 잡고
    ai_status='processing'으로 갱신 후 반환. 동시 워커 중복 처리 방지.
    notice_content(본문 URL) 함께 로드.
    """
    stmt = (
        select(Notice)
        .where(Notice.id == notice_id, Notice.ai_status == "pending")
        .options(selectinload(Notice.notice_content), selectinload(Notice.college))
        .with_for_update(skip_locked=True)
    )
    result = session.execute(stmt)
    notice = result.scalar_one_or_none()
    if notice is None:
        return None
    notice.ai_status = "processing"
    notice.ai_processing_started_at = datetime.now(UTC)
    session.flush()
    return notice


def update_ai_result_sync(
    session: Session,
    notice_id: uuid.UUID,
    ai_extracted_json: dict[str, Any],
    *,
    dates: list[dict[str, Any]] | None = None,
    eligibility: list[str] | None = None,
    hashtags: list[str] | None = None,
    taxonomy_rows: list[dict[str, str]] | None = None,
    only_if_processing: bool = False,
) -> int:
    """
    AI 처리 완료 시 ai_status='done', ai_extracted_json 및 투영 필드 저장 (동기, 워커용).
    taxonomy_rows가 전달되면 notice_taxonomy_mappings를 notice_id 기준으로 교체한다.
    only_if_processing=True면 현재 행이 processing일 때만 갱신. 반환: 매칭 행 수.
    """
    values: dict[str, Any] = {
        "ai_status": "done",
        "ai_extracted_json": ai_extracted_json,
        "ai_processing_started_at": None,
    }
    if dates is not None:
        values["dates"] = dates
    if eligibility is not None:
        values["eligibility"] = eligibility
    if hashtags is not None:
        values["hashtags"] = hashtags
    cond = Notice.id == notice_id
    if only_if_processing:
        cond = and_(cond, Notice.ai_status == "processing")
    result = session.execute(update(Notice).where(cond).values(**values))
    rowcount = int(result.rowcount or 0)
    if rowcount > 0 and taxonomy_rows is not None:
        _replace_notice_taxonomy_rows_sync(
            session=session,
            notice_id=notice_id,
            taxonomy_rows=taxonomy_rows,
        )
    session.flush()
    return rowcount


def reset_ai_notice_to_pending_after_failed_extraction_sync(session: Session, notice_id: uuid.UUID) -> int:
    """HTTP/LLM 실패 후 재시도 가능하도록 processing → pending. 반환: 매칭 행 수."""
    result = session.execute(
        update(Notice)
        .where(Notice.id == notice_id, Notice.ai_status == "processing")
        .values(ai_status="pending", ai_processing_started_at=None)
    )
    session.flush()
    return int(result.rowcount or 0)


def reset_stale_ai_processing_notices_sync(session: Session, *, older_than_seconds: int) -> int:
    """
    ai_status=processing 이고 선점 시각이 임계보다 오래된 행을 pending으로 되돌린다.
    ai_processing_started_at IS NULL 인 processing(레거시)도 임계 경과 시 복구 대상에 포함.
    """
    if older_than_seconds <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    result = session.execute(
        update(Notice)
        .where(
            Notice.ai_status == "processing",
            or_(Notice.ai_processing_started_at.is_(None), Notice.ai_processing_started_at < cutoff),
        )
        .values(ai_status="pending", ai_processing_started_at=None)
    )
    session.flush()
    return int(result.rowcount or 0)


def list_pending_notice_ids_for_ai_requeue_sync(
    session: Session,
    *,
    older_than_seconds: int,
    limit: int = 200,
) -> list[uuid.UUID]:
    """
    AI가 오래 pending인 공지 id 목록. 크롤 후 enqueue 실패 등 복구용.
    updated_at 기준으로 최소 대기 시간을 두어 방금 적재된 행과 구분한다.
    """
    if older_than_seconds <= 0 or limit <= 0:
        return []
    threshold = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stmt = (
        select(Notice.id)
        .where(
            Notice.ai_status == "pending",
            Notice.deleted_at.is_(None),
            Notice.updated_at < threshold,
        )
        .order_by(Notice.updated_at.asc())
        .limit(limit)
    )
    rows = session.execute(stmt).scalars().all()
    return list(rows)


def _replace_notice_taxonomy_rows_sync(
    *,
    session: Session,
    notice_id: uuid.UUID,
    taxonomy_rows: list[dict[str, str]],
) -> None:
    """notice_id의 taxonomy 매핑을 전달된 행 목록으로 완전 교체한다."""
    session.execute(delete(NoticeTaxonomyMapping).where(NoticeTaxonomyMapping.notice_id == notice_id))
    if not taxonomy_rows:
        return

    cleaned_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in taxonomy_rows:
        main_category = str(row.get("main_category", "")).strip()
        sub_category = str(row.get("sub_category", "")).strip()
        if not main_category or not sub_category:
            continue
        key = (main_category, sub_category)
        if key in seen:
            continue
        seen.add(key)
        cleaned_rows.append(
            {
                "notice_id": notice_id,
                "main_category": main_category,
                "sub_category": sub_category,
            }
        )
    if not cleaned_rows:
        return

    session.execute(insert(NoticeTaxonomyMapping).values(cleaned_rows))


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


def _sorted_notice_drafts(notices: Sequence[NoticeDraft]) -> list[NoticeDraft]:
    """
    벌크 upsert 전 저장소 경계에서 다시 정규화한다.

    - 동일 (college_id, external_id)가 한 배치에 여러 번 오면 마지막 draft만 유지
    - 이후 (college_id, external_id) 오름차순 정렬로 row lock 순서를 통일
    """
    deduped: dict[tuple[uuid.UUID, str], NoticeDraft] = {}
    for draft in notices:
        deduped[(draft.college_id, draft.external_id)] = draft
    return sorted(deduped.values(), key=lambda d: (str(d.college_id), d.external_id))


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


def _notice_upsert_set_excluded(stmt: Any) -> dict[str, Any]:
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
    drafts: Sequence[NoticeDraft],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> list[tuple[uuid.UUID, str]]:
    """content_url이 있는 draft 중 key_to_id에 없는 (college_id, external_id) 목록."""
    missing: list[tuple[uuid.UUID, str]] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    for d in drafts:
        if not d.content_url:
            continue
        k = (d.college_id, d.external_id)
        if k in key_to_id or k in seen:
            continue
        seen.add(k)
        missing.append(k)
    return missing


def _build_missing_notice_stmt(
    missing: list[tuple[uuid.UUID, str]],
) -> Any:
    """missing 기준 Notice id/college_id/external_id 조회용 select statement. len(missing) >= 1 전제."""
    if len(missing) == 1:
        (cid, eid) = missing[0]
        return select(Notice.id, Notice.college_id, Notice.external_id).where(
            Notice.college_id == cid, Notice.external_id == eid
        )
    return select(Notice.id, Notice.college_id, Notice.external_id).where(
        tuple_(Notice.college_id, Notice.external_id).in_(missing)
    )


def _build_bulk_upsert_stmt(drafts: Sequence[NoticeDraft]) -> tuple[Any, list[NoticeDraft]]:
    """
    Bulk upsert용 Insert statement와 정렬된 drafts 반환. 데드락 방지를 위해
    (college_id, external_id) 기준 오름차순 정렬. dict 변환은 SQL 직전에만 수행.
    """
    sorted_drafts = _sorted_notice_drafts(drafts)
    notice_rows = [_notice_values_no_content(_draft_to_notice_dict(d)) for d in sorted_drafts]
    base = insert(Notice).values(notice_rows)
    stmt = base.on_conflict_do_update(
        index_elements=["college_id", "external_id"],
        index_where=Notice.deleted_at.is_(None),
        set_=_notice_upsert_set_excluded(base),
        where=Notice.content_hash.is_distinct_from(base.excluded.content_hash),
    ).returning(Notice.id, Notice.college_id, Notice.external_id)
    return stmt, sorted_drafts


def _build_upsert_stmt_for_rows(notice_rows: list[dict[str, Any]]) -> Any:
    """배치 단위 upsert용 Insert statement. notice_rows는 이미 (college_id, external_id) 정렬된 일부."""
    base = insert(Notice).values(notice_rows)
    return base.on_conflict_do_update(
        index_elements=["college_id", "external_id"],
        index_where=Notice.deleted_at.is_(None),
        set_=_notice_upsert_set_excluded(base),
        where=Notice.content_hash.is_distinct_from(base.excluded.content_hash),
    ).returning(Notice.id, Notice.college_id, Notice.external_id)


def _build_notice_contents_upsert_payloads(
    drafts: Sequence[NoticeDraft],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> list[dict[str, Any]]:
    """drafts와 key_to_id로 notice_contents upsert용 to_insert 리스트 구성(DB insert용 dict만). sync/async 공통."""
    deduped: dict[uuid.UUID, dict[str, Any]] = {}
    for d in drafts:
        if not d.content_url:
            continue
        nid = key_to_id.get((d.college_id, d.external_id))
        if nid is None:
            continue
        deduped[nid] = {"notice_id": nid, "content_url": d.content_url}
    return [deduped[nid] for nid in sorted(deduped)]


def _iter_batches(
    rows: Sequence[dict[str, Any]],
    batch_size: int | None = None,
) -> Iterator[Sequence[dict[str, Any]]]:
    """큰 VALUES 절을 잘라 row lock 점유 시간과 WAL burst를 줄인다."""
    size = batch_size or BULK_UPSERT_BATCH_SIZE
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


async def _fill_key_to_id_from_notices(
    session: AsyncSession,
    drafts: Sequence[NoticeDraft],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """RETURNING에 없는(동일 content_hash) 행의 notice_id를 조회해 key_to_id 보완. 본문 백필 가능."""
    missing = _keys_with_content_but_missing(drafts, key_to_id)
    if not missing:
        return
    stmt = _build_missing_notice_stmt(missing)
    result = await session.execute(stmt)
    for row in result.all():
        nid, cid, eid = row[0], row[1], row[2]
        key_to_id[(cid, eid)] = nid


def _fill_key_to_id_from_notices_sync(
    session: Session,
    drafts: Sequence[NoticeDraft],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """동기: RETURNING에 없는 행의 notice_id 조회해 key_to_id 보완."""
    missing = _keys_with_content_but_missing(drafts, key_to_id)
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
    여러 공지를 한 트랜잭션으로 bulk upsert. 500행 단위 배치로 execute하여 락/WAL 부담 완화.
    content_url이 있으면 notice_contents도 upsert. 내부 전달은 NoticeDraft 유지, DB 직전에만 dict 변환.
    content_hash가 실제로 변한 행만 업데이트하고, RETURNING id로 신규/변경 공지 ID만 반환 (AI 큐 대상).
    """
    if not notices:
        return []
    sorted_drafts = _sorted_notice_drafts(notices)
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    ids: list[uuid.UUID] = []
    for i in range(0, len(sorted_drafts), BULK_UPSERT_BATCH_SIZE):
        batch = sorted_drafts[i : i + BULK_UPSERT_BATCH_SIZE]
        notice_rows = [_notice_values_no_content(_draft_to_notice_dict(d)) for d in batch]
        stmt = _build_upsert_stmt_for_rows(notice_rows)
        result = await session.execute(stmt)
        for row in result.all():
            nid, cid, eid = row[0], row[1], row[2]
            key_to_id[(cid, eid)] = nid
            ids.append(nid)
        await session.flush()
    await _fill_key_to_id_from_notices(session, sorted_drafts, key_to_id)
    await _upsert_notice_contents_bulk_from_drafts(session, sorted_drafts, key_to_id)
    return ids


def upsert_notices_bulk_sync(
    session: Session,
    notices: Sequence[NoticeDraft],
) -> list[uuid.UUID]:
    """
    동기 bulk upsert (Celery 워커용). 500행 단위 배치로 execute하여 락/WAL 부담 완화.
    content_url이 있으면 notice_contents도 upsert. 내부 전달은 NoticeDraft 유지, DB 직전에만 dict 변환.
    content_hash가 실제로 변한 행만 업데이트, RETURNING id로 신규/변경 공지 ID만 반환.
    """
    if not notices:
        return []
    sorted_drafts = _sorted_notice_drafts(notices)
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    ids: list[uuid.UUID] = []
    for i in range(0, len(sorted_drafts), BULK_UPSERT_BATCH_SIZE):
        batch = sorted_drafts[i : i + BULK_UPSERT_BATCH_SIZE]
        notice_rows = [_notice_values_no_content(_draft_to_notice_dict(d)) for d in batch]
        stmt = _build_upsert_stmt_for_rows(notice_rows)
        result = session.execute(stmt)
        for row in result.all():
            nid, cid, eid = row[0], row[1], row[2]
            key_to_id[(cid, eid)] = nid
            ids.append(nid)
        session.flush()
    _fill_key_to_id_from_notices_sync(session, sorted_drafts, key_to_id)
    _upsert_notice_contents_bulk_from_drafts_sync(session, sorted_drafts, key_to_id)
    return ids


def _upsert_notice_contents_bulk_from_drafts_sync(
    session: Session,
    drafts: Sequence[NoticeDraft],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """drafts와 key_to_id로 notice_contents bulk upsert (동기). notice_id 순 정렬로 락 순서 통일."""
    to_insert = _build_notice_contents_upsert_payloads(drafts, key_to_id)
    if not to_insert:
        return
    for batch in _iter_batches(to_insert):
        ins = insert(NoticeContent).values(batch)
        stmt = ins.on_conflict_do_update(
            index_elements=["notice_id"],
            set_={"content_url": ins.excluded.content_url, "updated_at": datetime.now(UTC)},
        )
        session.execute(stmt)
    session.flush()


async def _upsert_notice_contents_bulk_from_drafts(
    session: AsyncSession,
    drafts: Sequence[NoticeDraft],
    key_to_id: dict[tuple[uuid.UUID, str], uuid.UUID],
) -> None:
    """drafts와 key_to_id로 notice_contents bulk upsert (비동기). notice_id 순 정렬로 락 순서 통일."""
    to_insert = _build_notice_contents_upsert_payloads(drafts, key_to_id)
    if not to_insert:
        return
    for batch in _iter_batches(to_insert):
        ins = insert(NoticeContent).values(batch)
        stmt = ins.on_conflict_do_update(
            index_elements=["notice_id"],
            set_={"content_url": ins.excluded.content_url, "updated_at": datetime.now(UTC)},
        )
        await session.execute(stmt)
    await session.flush()
