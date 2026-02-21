"""
내부 전용 API (Cron·관리). 보안 키는 Header만 허용(X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
Query 파라미터 시크릿 미지원(Access Log 유출 방지). college별 분산락으로 중복 enqueue 방지.
"""

import asyncio
import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
<<<<<<< ours
=======
from fastapi.responses import JSONResponse
>>>>>>> theirs
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE
from app.core.database import get_db
<<<<<<< ours
from app.core.deps import get_redis_blocklist
from app.core.redis import acquire_trigger_lock
=======
from app.core.deps import get_redis_trigger_lock
from app.core.redis import (
    RedisLockUnavailableError,
    acquire_trigger_lock,
    release_trigger_lock,
)
>>>>>>> theirs
from app.repositories.crawl_run_repository import get_recent_crawl_runs

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger(__name__)

# 단과대별 크롤 시작 시간 분산(Thundering Herd 방지). 초 단위. 예: 300 = 5분 간격.
CRAWL_STAGGER_SECONDS = 300


def _validate_trigger_secret(
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
) -> None:
    """CRAWL_TRIGGER_SECRET 검증. Header만 사용(Query 미허용). timing-safe 비교. 실패 시 HTTPException."""
    if not settings.crawl_trigger_secret:
        raise HTTPException(
            status_code=503,
            detail="Crawl trigger not configured (CRAWL_TRIGGER_SECRET missing)",
        )
    provided = (
        x_crawl_trigger_secret
        or (authorization and authorization.startswith("Bearer ") and authorization[7:].strip())
    ) or ""
    expected = settings.crawl_trigger_secret.get_secret_value()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing crawl trigger secret")


@router.post("/trigger-crawl")
async def post_trigger_crawl(
    college_code: str | None = Query(
        None,
        description="단과대 코드(engineering, science, ...). 없으면 전체 순차 enqueue.",
    ),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
<<<<<<< ours
    redis_client: Any = Depends(get_redis_blocklist),
=======
    redis_client: Any = Depends(get_redis_trigger_lock),
>>>>>>> theirs
) -> dict:
    """
    크롤 태스크 enqueue. 보안 키는 Header만 필수. college별 Redis 분산락(SET NX EX)으로 중복 enqueue 방지.
    락 실패 시 해당 college는 스킵. 워커 완료/예외 시 락 조기 해제.
    """
    _validate_trigger_secret(x_crawl_trigger_secret, authorization)

    from app.services.tasks import crawl_college_task

    if college_code is not None:
        if college_code not in COLLEGE_CODE_TO_MODULE:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown college_code: {college_code}. Valid: {list(COLLEGE_CODE_TO_MODULE.keys())}",
            )
        codes = [college_code]
    else:
        codes = list(COLLEGE_CODE_TO_MODULE.keys())

    task_ids: list[dict] = []
    skipped: list[str] = []
    for i, code in enumerate(codes):
<<<<<<< ours
        if redis_client is not None:
            acquired = await acquire_trigger_lock(redis_client, code)
=======
        lock_token: str | None = None
        if redis_client is not None:
            try:
                acquired, lock_token = await acquire_trigger_lock(redis_client, code)
            except RedisLockUnavailableError:
                logger.exception("Trigger lock unavailable (Redis error) for college=%s", code)
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Service temporarily unavailable",
                        "code": "REDIS_LOCK_UNAVAILABLE",
                    },
                )
>>>>>>> theirs
            if not acquired:
                skipped.append(code)
                continue
        countdown = i * CRAWL_STAGGER_SECONDS if len(codes) > 1 else 0
        try:
            result = await asyncio.to_thread(
                crawl_college_task.apply_async,
<<<<<<< ours
                args=[code],
=======
                args=[code, lock_token],
>>>>>>> theirs
                countdown=countdown,
            )
        except Exception as e:
            logger.exception("trigger-crawl apply_async failed: code=%s", code)
<<<<<<< ours
            raise HTTPException(
                status_code=503,
                detail="Crawl task enqueue failed",
=======
            if redis_client is not None and lock_token:
                await release_trigger_lock(redis_client, code, lock_token)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service temporarily unavailable",
                    "code": "CRAWL_ENQUEUE_FAILED",
                },
>>>>>>> theirs
            ) from e
        task_ids.append({"college_code": code, "task_id": result.id, "countdown_sec": countdown})

    out: dict = {"enqueued": len(task_ids), "tasks": task_ids}
    if skipped:
        out["skipped"] = skipped
    return out


@router.get("/crawl-stats")
async def get_crawl_stats(
    limit: int = Query(50, ge=1, le=200, description="최근 N건"),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    최근 크롤 실행 이력. 단과대별 last_run_at, status, notices_upserted, error_message.
    보안 키 필수. Header만 사용 (X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
    """
    _validate_trigger_secret(x_crawl_trigger_secret, authorization)
    runs = await get_recent_crawl_runs(session, limit=limit)
    return {"runs": runs, "limit": limit}
