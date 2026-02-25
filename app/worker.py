"""
Celery 워커 진입점. broker=Redis, result_backend 설정.
redis://·rediss://(TLS) 모두 지원. Railway Redis TLS 시 ssl_cert_reqs 적용.
"""

import logging
import ssl

from celery import Celery

from app.core.config import settings

logger = logging.getLogger(__name__)

# broker_url 없으면 기본값(로컬 개발 시 수동 설정 필요). 공백 문자열은 미설정으로 취급.
_raw_redis_url = (settings.redis_url or "").strip()
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
    broker_transport_options={"visibility_timeout": 3600},  # 1시간. 크롤 태스크 장시간 대비.
    task_acks_late=True,  # 완료 후 ack. 크래시 시 재전달 가능.
    task_reject_on_worker_lost=True,  # 워커 강제 종료 시 메시지 반환해 재큐.
    worker_prefetch_multiplier=1,  # 한 워커가 한 번에 하나의 태스크만 prefetch.
    beat_schedule={
        "close-stale-crawl-runs": {
            "task": "app.services.tasks.close_stale_crawl_runs_task",
            "schedule": 900.0,  # 15분마다. CRAWL_RUN_STALE_SECONDS보다 짧게 권장.
        },
    },
)

# rediss://(TLS)일 때 SSL 옵션 적용. 인증서 검증 필수(MITM 방지).
if broker_url.startswith("rediss://"):
    ssl_options = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    if getattr(settings, "redis_ca_certs", None):
        ssl_options["ssl_ca_certs"] = settings.redis_ca_certs
    app.conf.broker_use_ssl = ssl_options
    app.conf.redis_backend_use_ssl = ssl_options

# 태스크 등록 (app.services.tasks가 이 app에 바인딩되도록 로드)
from app.services import tasks  # noqa: F401, E402

# Sentry: 워커 진입 시 초기화 (3단계 요구사항)
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            integrations=[
                CeleryIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            traces_sample_rate=0.1,
            environment=settings.environment,
        )
        logger.info("Sentry initialized for worker")
    except ImportError:
        logger.error(
            "Sentry is enabled (SENTRY_DSN set) but sentry_sdk is missing. Install sentry-sdk."
        )
