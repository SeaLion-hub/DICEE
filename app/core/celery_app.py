"""
Celery 앱 단일 진입점. broker=Redis, result_backend, beat_schedule, include(명시적 paths).
태스크 발견은 include 리스트로만 수행. autodiscover 전체 스캔 사용 안 함.
"""

import logging
import os
import ssl

# Celery CLI가 이 모듈을 로드할 때 APP_ENTRY가 없으면 celery로 설정. Settings() 검증 통과용.
os.environ.setdefault("APP_ENTRY", "celery")

from celery import Celery
from celery.signals import worker_init
from kombu import Queue  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.crawler_config import validate_crawler_contract

logger = logging.getLogger(__name__)


def _ensure_celery_entry() -> None:
    """워커/beat 기동 시 APP_ENTRY=celery 여부 검사. api일 때는 RuntimeError."""
    if settings.app_entry != "celery":
        raise RuntimeError(
            "Celery process must run with APP_ENTRY=celery. "
            f"Current APP_ENTRY={settings.app_entry!r}. Set APP_ENTRY=celery for worker/beat."
        )


# Celery 전용 Redis URL. 비어 있으면 앱과 동일 redis_url 사용.
_raw_celery_url = (getattr(settings, "redis_celery_url", None) or settings.redis.redis_url or "").strip()
broker_url = _raw_celery_url or "redis://localhost:6379/0"
result_backend = broker_url

app = Celery("app", broker=broker_url, backend=result_backend, include=["app.services.tasks"])

# 라우팅 도입 시 태스크는 명명 큐로만 전달됨.
# 워커는 소비할 큐를 반드시 명시해야 함:
# -Q critical,crawl,ai (단일 워커) 또는 큐별 분리.
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
    task_queues=(Queue("critical"), Queue("crawl"), Queue("ai")),
    task_routes={
        "app.services.tasks.close_stale_crawl_runs_task": {"queue": "critical"},
        "app.services.tasks.crawl_college_task": {"queue": "crawl"},
        "app.services.tasks.process_notice_ai_task": {"queue": "ai"},
        "app.services.tasks.drain_content_spool_task": {"queue": "critical"},
    },
    beat_schedule={
        "close-stale-crawl-runs": {
            "task": "app.services.tasks.close_stale_crawl_runs_task",
            "schedule": 900.0,
        },
        "drain-content-spool": {
            "task": "app.services.tasks.drain_content_spool_task",
            "schedule": 300.0,
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


@worker_init.connect
def _on_worker_init(**kwargs):
    """워커 프로세스 기동 시에만 APP_ENTRY=celery 검사. API에서 tasks import 시에는 검사하지 않음."""
    _ensure_celery_entry()
    validate_crawler_contract()


@app.on_after_configure.connect
def _on_after_configure(**kwargs):
    """프로덕션 워커: API와 동일한 예외/로그 마스킹 필터 등록. development: [DEV] 접두사."""
    root = logging.getLogger()
    env = (settings.environment or "").strip().lower()
    if env == "production":
        from app.core.logging_safety import ProductionExceptionFilter

        if not any(isinstance(f, ProductionExceptionFilter) for f in root.filters):
            root.addFilter(ProductionExceptionFilter())
    elif env == "development":
        from app.core.logging_context import DevelopmentLogFilter

        if not any(isinstance(f, DevelopmentLogFilter) for f in root.filters):
            root.addFilter(DevelopmentLogFilter())
