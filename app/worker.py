"""
Celery 워커 진입점. app은 app.core.celery_app에서 로드. 태스크 발견은 include로만 수행.
실행: celery -A app.core.celery_app:app worker -O fair
"""

import logging
from typing import Any, cast

from app.core.config import settings

logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        from app.core.sentry_config import before_send_scrub

        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            integrations=[
                CeleryIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            traces_sample_rate=0.1,
            environment=settings.environment,
            before_send=cast(Any, before_send_scrub),
        )
        logger.info("Sentry initialized for worker")
    except ImportError:
        logger.error("Sentry is enabled (SENTRY_DSN set) but sentry_sdk is missing. Install sentry-sdk.")
    except Exception as e:
        logger.warning("Sentry init failed (worker continues without Sentry): %s", e, exc_info=True)
