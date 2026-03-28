"""CrawlDispatcherPort implementation backed by Celery apply_async."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.core.metrics import (
    CRAWL_DISPATCH_BACKPRESSURE_TOTAL,
    CRAWL_DISPATCH_ENQUEUED_TOTAL,
    CRAWL_DISPATCH_MEMORY_MB,
    CRAWL_DISPATCH_NET_RECV_MB,
    CRAWL_DISPATCH_NET_SENT_MB,
    increment,
    set_gauge,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ResourceSnapshot:
    memory_mb: float | None
    net_sent_mb: float | None
    net_recv_mb: float | None


class CeleryCrawlDispatcher:
    """CrawlDispatcherPort implementation with lightweight resource-aware backpressure."""

    class _CeleryTaskProtocol(Protocol):
        def apply_async(
            self,
            args: list[Any] | None = None,
            kwargs: dict[str, Any] | None = None,
            countdown: int | None = None,
            **options: Any,
        ) -> Any: ...

    async def enqueue(
        self,
        college_code: str,
        lock_token: str | None,
        countdown: int,
        enqueued_at: float,
    ) -> str:
        """Dispatch crawl task and return task_id while preserving existing method contract."""
        from app.services.tasks import crawl_college_task

        task: CeleryCrawlDispatcher._CeleryTaskProtocol = crawl_college_task

        labels = {"college_code": college_code}
        snapshot = await asyncio.to_thread(_collect_resource_snapshot)
        _record_snapshot_metrics(snapshot, labels=labels)

        base_countdown = max(0, int(countdown))
        extra_backpressure = _compute_backpressure_seconds(snapshot.memory_mb)
        effective_countdown = base_countdown + extra_backpressure

        if extra_backpressure > 0:
            increment(CRAWL_DISPATCH_BACKPRESSURE_TOTAL, 1, labels=labels)
            logger.info(
                (
                    "crawl dispatch backpressure applied: "
                    "college_code=%s base_countdown=%s extra_countdown=%s memory_mb=%.1f"
                ),
                college_code,
                base_countdown,
                extra_backpressure,
                float(snapshot.memory_mb or 0.0),
            )

        result = await asyncio.to_thread(
            task.apply_async,
            args=[college_code, lock_token],
            kwargs={"enqueued_at": enqueued_at},
            countdown=effective_countdown,
        )
        increment(CRAWL_DISPATCH_ENQUEUED_TOTAL, 1, labels=labels)
        return str(result.id)


def _collect_resource_snapshot() -> _ResourceSnapshot:
    """Best-effort process memory/network snapshot. Fail-open when psutil is unavailable."""
    try:
        import psutil

        proc = psutil.Process()
        mem_mb = float(proc.memory_info().rss) / (1024 * 1024)
        net = psutil.net_io_counters()
        sent_mb = float(net.bytes_sent) / (1024 * 1024)
        recv_mb = float(net.bytes_recv) / (1024 * 1024)
        return _ResourceSnapshot(
            memory_mb=mem_mb,
            net_sent_mb=sent_mb,
            net_recv_mb=recv_mb,
        )
    except Exception:
        logger.debug("psutil snapshot unavailable; continuing without resource backpressure", exc_info=True)
        return _ResourceSnapshot(memory_mb=None, net_sent_mb=None, net_recv_mb=None)


def _record_snapshot_metrics(snapshot: _ResourceSnapshot, *, labels: dict[str, str]) -> None:
    if snapshot.memory_mb is not None:
        set_gauge(CRAWL_DISPATCH_MEMORY_MB, snapshot.memory_mb, labels=labels)
    if snapshot.net_sent_mb is not None:
        set_gauge(CRAWL_DISPATCH_NET_SENT_MB, snapshot.net_sent_mb, labels=labels)
    if snapshot.net_recv_mb is not None:
        set_gauge(CRAWL_DISPATCH_NET_RECV_MB, snapshot.net_recv_mb, labels=labels)


def _compute_backpressure_seconds(memory_mb: float | None) -> int:
    """Convert memory pressure into extra countdown with capped linear steps."""
    if memory_mb is None:
        return 0
    soft_limit = int(getattr(settings, "celery_dispatch_memory_soft_limit_mb", 0) or 0)
    step = int(getattr(settings, "celery_dispatch_backpressure_step_seconds", 0) or 0)
    max_extra = int(getattr(settings, "celery_dispatch_backpressure_max_seconds", 0) or 0)

    if soft_limit <= 0 or step <= 0 or max_extra <= 0:
        return 0
    if memory_mb <= soft_limit:
        return 0

    overflow_ratio = (memory_mb - soft_limit) / soft_limit
    levels = max(1, math.ceil(overflow_ratio))
    return min(max_extra, levels * step)
