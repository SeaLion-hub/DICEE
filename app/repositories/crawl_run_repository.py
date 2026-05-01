"""
CrawlRun Repository. crawl_run_tasks(idempotency) + crawl_runs(run data).

crawl_runs 계약: 모델은 복합 PK (id, started_at). 애플리케이션은 id당 1행만 생성.
조회/갱신 시 id 단독 + order_by(started_at.desc()).limit(1)로 결정적 1행 사용.
동일 id 복수 행 생성 금지(create_or_update가 기존 행 갱신만 수행).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.constants import CrawlRunStatus
from app.domain.contracts.crawl_contracts import CrawlRunRow, IngestionFreshnessRow
from app.models.college import College
from app.models.college_source import CollegeSource
from app.models.crawl_run import CrawlRun
from app.models.crawl_run_task import CrawlRunTask
from app.models.ingestion_attempt import IngestionAttempt


def _task_id_to_uuid(task_id: str) -> uuid.UUID:
    """Celery task_id string to UUID. 빈 문자열 또는 비정상 형식 시 ValueError 발생(idempotency/재시도 추적 유지)."""
    if not task_id or not str(task_id).strip():
        raise ValueError("task_id is required and must be a non-empty valid UUID string")
    try:
        return uuid.UUID(str(task_id).strip())
    except (ValueError, TypeError) as e:
        raise ValueError(f"task_id must be a valid UUID string (got {type(task_id).__name__!r}): {e}") from e


def ensure_crawl_run_task_sync(session: Session, task_id: str) -> uuid.UUID:
    """
    Idempotency: (task_id, run_id) in crawl_run_tasks. 재시도 시 동일 task_id로 같은 run_id 반환.
    반환: run_id (기존 또는 새로 생성).
    """
    task_uuid = _task_id_to_uuid(task_id)
    run_id = uuid.uuid4()
    stmt = (
        insert(CrawlRunTask)
        .values(
            celery_task_id=task_uuid,
            run_id=run_id,
        )
        .on_conflict_do_nothing(index_elements=["celery_task_id"])
    )
    session.execute(stmt)
    session.flush()
    got = session.execute(
        select(CrawlRunTask.run_id).where(CrawlRunTask.celery_task_id == task_uuid).limit(1)
    ).scalar_one_or_none()
    if got is not None:
        return got
    return run_id


def create_or_update_crawl_run_sync(
    session: Session,
    run_id: uuid.UUID,
    college_id: uuid.UUID,
) -> CrawlRun:
    """
    run_id로 crawl_runs 1건 생성 또는 재시도 시 갱신(상태 초기화, started_at은 최초 값 유지).
    계약: id당 최대 1행. 조회는 id 단독 사용(복합 PK이지만 현재 생성 전략상 1행만 존재).
    """
    now = datetime.now(UTC)
    existing = session.execute(
        select(CrawlRun).where(CrawlRun.id == run_id).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if existing:
        existing.status = CrawlRunStatus.RUNNING.value
        existing.notices_upserted = 0
        existing.finished_at = None
        existing.error_message = None
        existing.processed_count = 0
        existing.checkpointed_at = None
        session.flush()
        session.refresh(existing)
        return existing
    run = CrawlRun(
        id=run_id,
        college_id=college_id,
        started_at=now,
        status=CrawlRunStatus.RUNNING.value,
        notices_upserted=0,
        finished_at=None,
        error_message=None,
        processed_count=0,
        checkpointed_at=None,
    )
    session.add(run)
    session.flush()
    session.refresh(run)
    return run


def update_crawl_run_sync(
    session: Session,
    run_id: uuid.UUID,
    *,
    finished_at: datetime | None = None,
    status: str | None = None,
    notices_upserted: int | None = None,
    error_message: str | None = None,
    processed_count: int | None = None,
    checkpointed_at: datetime | None = None,
) -> CrawlRun | None:
    """
    run_id로 crawl_runs 1건 갱신 (동기, 워커용).
    계약: id 단독 조회. run_id당 1행 전제.
    """
    row = session.execute(
        select(CrawlRun).where(CrawlRun.id == run_id).order_by(CrawlRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if not row:
        return None
    if finished_at is not None:
        row.finished_at = finished_at
    if status is not None:
        row.status = status
    if notices_upserted is not None:
        row.notices_upserted = notices_upserted
    if error_message is not None:
        row.error_message = error_message
    if processed_count is not None:
        row.processed_count = processed_count
    if checkpointed_at is not None:
        row.checkpointed_at = checkpointed_at
    session.flush()
    session.refresh(row)
    return row


def update_crawl_run_checkpoint_sync(
    session: Session,
    run_id: uuid.UUID,
    processed_count: int,
    checkpointed_at: datetime,
) -> CrawlRun | None:
    """
    run_id의 체크포인트만 갱신. 청크 upsert와 동일 트랜잭션·같은 세션에서 호출해
    진행률과 실데이터를 한 커밋에 묶을 때 사용.
    """
    return update_crawl_run_sync(
        session,
        run_id,
        processed_count=processed_count,
        checkpointed_at=checkpointed_at,
    )


def close_stale_running_runs_sync(
    session: Session,
    older_than_seconds: float,
) -> int:
    """
    status=RUNNING 이면서 started_at이 older_than_seconds보다 오래된 행을 FAILED로 정리.
    장애로 완료 처리되지 않은 잔존 RUNNING 정리. Celery 주기 태스크에서 호출.
    반환: 업데이트된 행 수.
    """
    now = datetime.now(UTC)
    threshold = now - timedelta(seconds=older_than_seconds)
    stmt = (
        update(CrawlRun)
        .where(
            CrawlRun.status == CrawlRunStatus.RUNNING.value,
            CrawlRun.started_at < threshold,
        )
        .values(
            status=CrawlRunStatus.FAILED.value,
            error_message="Stale run detected",
            finished_at=now,
        )
    )
    result = session.execute(stmt)
    return result.rowcount if result.rowcount is not None else 0


async def fetch_source_freshness_async(session: AsyncSession) -> list[IngestionFreshnessRow]:
    """primary college_sources별 최근 ingestion_attempt 1건."""
    latest_attempt = (
        select(
            IngestionAttempt.college_source_id.label("college_source_id"),
            IngestionAttempt.status.label("status"),
            IngestionAttempt.started_at.label("started_at"),
            IngestionAttempt.finished_at.label("finished_at"),
            IngestionAttempt.total_docs.label("total_docs"),
        )
        .distinct(IngestionAttempt.college_source_id)
        .order_by(IngestionAttempt.college_source_id, IngestionAttempt.started_at.desc())
        .subquery()
    )
    stmt = (
        select(
            College.external_id,
            latest_attempt.c.status,
            latest_attempt.c.started_at,
            latest_attempt.c.finished_at,
            latest_attempt.c.total_docs,
        )
        .join(College, CollegeSource.college_id == College.id)
        .outerjoin(latest_attempt, latest_attempt.c.college_source_id == CollegeSource.id)
        .where(
            CollegeSource.is_primary.is_(True),
            College.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    out: list[IngestionFreshnessRow] = []
    for ext_id, status, started_at, finished_at, total_docs in result.all():
        if status is None:
            out.append(
                IngestionFreshnessRow(
                    college_code=ext_id,
                    last_attempt_status=None,
                    last_attempt_started_at=None,
                    last_attempt_finished_at=None,
                    total_docs=None,
                )
            )
            continue
        out.append(
            IngestionFreshnessRow(
                college_code=ext_id,
                last_attempt_status=status,
                last_attempt_started_at=started_at,
                last_attempt_finished_at=finished_at,
                total_docs=int(total_docs) if total_docs is not None else None,
            )
        )
    return out


async def get_recent_crawl_runs(
    session: AsyncSession,
    limit: int = 50,
) -> list[CrawlRunRow]:
    """최근 크롤 실행 이력 (단과대 코드 포함). 프레젠테이션(isoformat)은 서비스/API에서 수행."""
    stmt = (
        select(CrawlRun, College.external_id)
        .join(College, CrawlRun.college_id == College.id)
        .order_by(CrawlRun.started_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        CrawlRunRow(
            college_code=ext_id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            notices_upserted=run.notices_upserted,
            error_message=run.error_message,
        )
        for run, ext_id in rows
    ]


class CrawlRunRepositoryAdapter:
    """CrawlStatsQueryPort 구현. get_recent_crawl_runs를 래핑하여 서비스에서 주입받을 수 있게 함."""

    async def fetch_recent(self, session: AsyncSession, limit: int) -> list[CrawlRunRow]:
        return await get_recent_crawl_runs(session, limit=limit)

    async def fetch_source_freshness(self, session: AsyncSession) -> list[IngestionFreshnessRow]:
        return await fetch_source_freshness_async(session)
