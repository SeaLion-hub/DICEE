"""IngestionAttempt 동기: FOR UPDATE 클레임·완료."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import IngestionAttemptStatus
from app.models.college_source import CollegeSource
from app.models.ingestion_attempt import IngestionAttempt


def try_begin_ingestion_attempt_sync(
    session: Session,
    *,
    college_source_id: uuid.UUID,
    celery_task_id: str | None,
) -> IngestionAttempt | None:
    """
    college_source 행을 잠근 뒤, 진행 중인 attempt가 있으면 None.
    없으면 RUNNING attempt 1건 생성 후 반환.
    DB: uq_ingestion_attempts_one_running_per_source(부분 유니크)로 이중 삽입 방지.
    경쟁 시 IntegrityError → None.
    """
    src = session.execute(
        select(CollegeSource).where(CollegeSource.id == college_source_id).with_for_update()
    ).scalar_one_or_none()
    if src is None:
        return None
    active = session.execute(
        select(IngestionAttempt.id)
        .where(
            IngestionAttempt.college_source_id == college_source_id,
            IngestionAttempt.status == IngestionAttemptStatus.RUNNING.value,
            IngestionAttempt.finished_at.is_(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    if active is not None:
        return None
    now = datetime.now(UTC)
    row = IngestionAttempt(
        college_source_id=college_source_id,
        status=IngestionAttemptStatus.RUNNING.value,
        celery_task_id=(celery_task_id or "")[:255] or None,
        checkpoint_pointer=None,
        total_batches=0,
        completed_batches=0,
        total_docs=0,
        total_chunks=0,
        heartbeat_counter=0,
        cancellation_requested=False,
        error_msg=None,
        started_at=now,
        finished_at=None,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return None
    session.refresh(row)
    return row


def add_ingestion_scheduled_docs_sync(session: Session, attempt_id: uuid.UUID, n: int) -> None:
    if n <= 0:
        return
    session.execute(
        update(IngestionAttempt)
        .where(IngestionAttempt.id == attempt_id)
        .values(total_docs=IngestionAttempt.total_docs + n)
    )


def increment_attempt_total_batches_sync(session: Session, attempt_id: uuid.UUID) -> None:
    session.execute(
        update(IngestionAttempt)
        .where(IngestionAttempt.id == attempt_id)
        .values(total_batches=IngestionAttempt.total_batches + 1)
    )


def increment_ingestion_heartbeat_sync(session: Session, attempt_id: uuid.UUID) -> None:
    session.execute(
        update(IngestionAttempt)
        .where(IngestionAttempt.id == attempt_id)
        .values(heartbeat_counter=IngestionAttempt.heartbeat_counter + 1)
    )


def mark_ingestion_attempt_success_sync(
    session: Session,
    attempt_id: uuid.UUID,
    *,
    total_docs: int | None = None,
) -> None:
    vals: dict = {
        "status": IngestionAttemptStatus.SUCCESS.value,
        "finished_at": datetime.now(UTC),
    }
    if total_docs is not None:
        vals["total_docs"] = total_docs
    session.execute(update(IngestionAttempt).where(IngestionAttempt.id == attempt_id).values(**vals))


def mark_ingestion_attempt_failed_sync(session: Session, attempt_id: uuid.UUID, error_msg: str) -> None:
    session.execute(
        update(IngestionAttempt)
        .where(IngestionAttempt.id == attempt_id)
        .values(
            status=IngestionAttemptStatus.FAILED.value,
            finished_at=datetime.now(UTC),
            error_msg=(error_msg or "")[:8000],
        )
    )


def increment_attempt_completed_batches_sync(session: Session, attempt_id: uuid.UUID) -> IngestionAttempt | None:
    """completed_batches SQL 단일 UPDATE로 원자 증가 후 행 반환."""
    session.execute(
        update(IngestionAttempt)
        .where(IngestionAttempt.id == attempt_id)
        .values(completed_batches=IngestionAttempt.completed_batches + 1)
    )
    return session.execute(
        select(IngestionAttempt).where(IngestionAttempt.id == attempt_id).limit(1)
    ).scalar_one_or_none()


def close_stale_running_ingestion_attempts_sync(
    session: Session,
    older_than_seconds: float,
) -> int:
    """RUNNING·미종료 attempt를 오래된 started_at 기준 FAILED로 정리."""
    now = datetime.now(UTC)
    threshold = now - timedelta(seconds=older_than_seconds)
    stmt = (
        update(IngestionAttempt)
        .where(
            IngestionAttempt.status == IngestionAttemptStatus.RUNNING.value,
            IngestionAttempt.started_at < threshold,
            IngestionAttempt.finished_at.is_(None),
        )
        .values(
            status=IngestionAttemptStatus.FAILED.value,
            finished_at=now,
            error_msg="Stale ingestion attempt",
        )
    )
    result = session.execute(stmt)
    return result.rowcount if result.rowcount is not None else 0


def maybe_finalize_attempt_after_batch_sync(session: Session, attempt: IngestionAttempt) -> None:
    """분리 모드: 모든 배치 처리 후 SUCCESS."""
    session.refresh(attempt)
    if attempt.status != IngestionAttemptStatus.RUNNING.value:
        return
    if attempt.total_batches <= 0:
        return
    if attempt.completed_batches < attempt.total_batches:
        return
    attempt.status = IngestionAttemptStatus.SUCCESS.value
    attempt.finished_at = datetime.now(UTC)
    session.flush()
