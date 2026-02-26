"""
Celery 앱 단일 진입점. broker=Redis, result_backend, beat_schedule, include(명시적 paths).
태스크 발견은 include 리스트로만 수행. autodiscover 전체 스캔 사용 안 함.
"""

import logging
import ssl

from celery import Celery

from app.core.config import settings

logger = logging.getLogger(__name__)


def _ensure_celery_entry() -> None:
    """워커/beat 기동 시 APP_ENTRY=celery 여부 검사. api일 때는 RuntimeError."""
    if settings.app_entry != "celery":
        raise RuntimeError(
            "Celery process must run with APP_ENTRY=celery. "
            f"Current APP_ENTRY={settings.app_entry!r}. Set APP_ENTRY=celery for worker/beat."
        )


_ensure_celery_entry()

_raw_redis_url = (settings.redis.redis_url or "").strip()
broker_url = _raw_redis_url or "redis://localhost:6379/0"
result_backend = _raw_redis_url or "redis://localhost:6379/0"

app = Celery(
    "app",
    broker=broker_url,
    backend=result_backend,
    include=["app.services.tasks"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    beat_schedule={
        "close-stale-crawl-runs": {
            "task": "app.services.tasks.close_stale_crawl_runs_task",
            "schedule": 900.0,
        },
    },
)

if broker_url.startswith("rediss://"):
    ssl_options: dict[str, str | ssl.VerifyMode] = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    ca = settings.redis.redis_ca_certs
    if ca is not None:
        ssl_options["ssl_ca_certs"] = ca
    app.conf.broker_use_ssl = ssl_options
    app.conf.redis_backend_use_ssl = ssl_options


@app.on_after_configure.connect
def _on_after_configure(**kwargs):
    """프로덕션 워커: API와 동일한 예외/로그 마스킹 필터 등록(스택·예외 메시지 원천 차단)."""
    if (settings.environment or "").strip().lower() == "production":
        from app.core.logging_safety import ProductionExceptionFilter
        root = logging.getLogger()
        if not any(isinstance(f, ProductionExceptionFilter) for f in root.filters):
            root.addFilter(ProductionExceptionFilter())
