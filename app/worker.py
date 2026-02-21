"""
Celery 워커 진입점. broker=Redis, result_backend 설정.
redis://·rediss://(TLS) 모두 지원. Railway Redis TLS 시 ssl_cert_reqs 적용.
"""

import logging
import ssl

from celery import Celery

from app.core.config import settings

logger = logging.getLogger(__name__)

# broker_url 없으면 기본값(로컬 개발 시 수동 설정 필요)
broker_url = settings.redis_url or "redis://localhost:6379/0"
result_backend = settings.redis_url or "redis://localhost:6379/0"

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
)

# rediss://(TLS)일 때 SSL 옵션 적용 (Railway Redis 등)
if broker_url.startswith("rediss://"):
    app.conf.broker_use_ssl = {
        "ssl_cert_reqs": ssl.CERT_NONE,  # Railway 등 자체 서명 인증서 대응
    }
    app.conf.redis_backend_use_ssl = {
        "ssl_cert_reqs": ssl.CERT_NONE,
    }

# 태스크 등록 (app.services.tasks가 이 app에 바인딩되도록 로드)
from app.services import tasks  # noqa: F401, E402

# Sentry: 워커 진입 시 초기화 (3단계 요구사항)
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[
                CeleryIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            traces_sample_rate=0.1,
            environment="production",
        )
        logger.info("Sentry initialized for worker")
    except ImportError:
        logger.error(
            "Sentry is enabled (SENTRY_DSN set) but sentry_sdk is missing. Install sentry-sdk."
        )
