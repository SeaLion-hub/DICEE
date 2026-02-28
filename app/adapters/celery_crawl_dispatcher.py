"""CrawlDispatcherPort 구현. Celery crawl_college_task 호출. Lazy import로 API 로드 시 Celery 부담 감소."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class CeleryCrawlDispatcher:
    """CrawlDispatcherPort 구현. enqueue 호출 시점에 crawl_college_task를 import."""

    async def enqueue(
        self,
        college_code: str,
        lock_token: str | None,
        countdown: int,
        enqueued_at: float,
    ) -> str:
        """apply_async를 asyncio.to_thread로 실행 후 task_id 반환. 예외 시 그대로 전파."""
        from app.services.tasks import crawl_college_task

        result = await asyncio.to_thread(
            crawl_college_task.apply_async,
            args=[college_code, lock_token],
            kwargs={"enqueued_at": enqueued_at},
            countdown=countdown,
        )
        return result.id
