"""CrawlRun Repository. 크롤 실행 이력 기록·조회."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.college import College
from app.models.crawl_run import CrawlRun


def create_crawl_run_sync(
    session: Session,
    college_id: int,
    celery_task_id: str,
) -> CrawlRun:
    """크롤 시작 시 1건 생성 또는 갱신(upsert). 재시도 시 동일 task_id로 상태 단일화."""
    now = datetime.now(UTC)
    stmt = insert(CrawlRun).values(
        college_id=college_id,
        celery_task_id=celery_task_id,
        started_at=now,
        status="running",
        notices_upserted=0,
        finished_at=None,
        error_message=None,
    ).on_conflict_do_update(
        index_elements=["celery_task_id"],
        set_={
            "started_at": now,
            "status": "running",
            "notices_upserted": 0,
            "finished_at": None,
            "error_message": None,
        },
    )
    session.execute(stmt)
    session.flush()
    row = session.execute(
        select(CrawlRun).where(CrawlRun.celery_task_id == celery_task_id).limit(1)
    ).scalar_one()
    session.refresh(row)
    return row


def update_crawl_run_sync(
    session: Session,
    celery_task_id: str,
    *,
    finished_at: datetime | None = None,
    status: str | None = None,
    notices_upserted: int | None = None,
    error_message: str | None = None,
) -> CrawlRun | None:
    """celery_task_id로 1건 갱신 (동기, 워커용)."""
    stmt = select(CrawlRun).where(CrawlRun.celery_task_id == celery_task_id).limit(1)
    result = session.execute(stmt)
    row = result.scalars().one_or_none()
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
