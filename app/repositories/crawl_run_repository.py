"""
CrawlRun Repository. crawl_run_tasks(idempotency) + crawl_runs(run data).

crawl_runs 계약: 모델은 복합 PK (id, started_at). 본 Repository는 "run_id(id)당 최대 1행"을
전제로 조회/갱신 시 id 단독 조건을 사용함. create_or_update는 동일 id 재호출 시 기존 행 갱신만 수행.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.constants import CrawlRunStatus
from app.models.college import College
from app.models.crawl_run import CrawlRun
from app.models.crawl_run_task import CrawlRunTask


def _task_id_to_uuid(task_id: str) -> uuid.UUID:
    """Celery task_id string to UUID. Handles empty string."""
    if not task_id:
        return uuid.uuid4()
    try:
        return uuid.UUID(task_id)
    except (ValueError, TypeError):
        return uuid.uuid4()


def ensure_crawl_run_task_sync(session: Session, task_id: str) -> uuid.UUID:
    """
    Idempotency: (task_id, run_id) in crawl_run_tasks. 재시도 시 동일 task_id로 같은 run_id 반환.
    반환: run_id (기존 또는 새로 생성).
    """
    task_uuid = _task_id_to_uuid(task_id)
    run_id = uuid.uuid4()
    stmt = insert(CrawlRunTask).values(
        celery_task_id=task_uuid,
        run_id=run_id,
    ).on_conflict_do_nothing(index_elements=["celery_task_id"])
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
    existing = session.execute(select(CrawlRun).where(CrawlRun.id == run_id).limit(1)).scalar_one_or_none()
    if existing:
        existing.status = CrawlRunStatus.RUNNING.value
        existing.notices_upserted = 0
        existing.finished_at = None
        existing.error_message = None
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
) -> CrawlRun | None:
    """
    run_id로 crawl_runs 1건 갱신 (동기, 워커용).
    계약: id 단독 조회. run_id당 1행 전제.
    """
    row = session.execute(select(CrawlRun).where(CrawlRun.id == run_id).limit(1)).scalar_one_or_none()
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
    session.flush()
    session.refresh(row)
    return row


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


async def get_recent_crawl_runs(
    session: AsyncSession,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """최근 크롤 실행 이력 (단과대 코드 포함). GET /internal/crawl-stats용."""
    stmt = (
        select(CrawlRun, College.external_id)
        .join(College, CrawlRun.college_id == College.id)
        .order_by(CrawlRun.started_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "college_code": ext_id,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "status": run.status,
            "notices_upserted": run.notices_upserted,
            "error_message": run.error_message,
        }
        for run, ext_id in rows
    ]
