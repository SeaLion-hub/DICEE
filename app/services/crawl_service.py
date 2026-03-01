"""
크롤 디스패처/서비스: config → get_*_links / scrape_*_detail.
Sync 진입점은 app.services.crawl 패키지에서 구현·re-export. 이 모듈은 async 경로 + re-export만 유지.
테스트가 crawl_service 모듈 속성으로 패치/접근하므로 아래 re-export 유지.
"""

from app.core.config import settings  # noqa: F401 (re-export for tests)
from app.core.crawl_rate_limit import get_host_rate_limiter_sync  # noqa: F401
from app.core.crawler_config import get_crawler  # noqa: F401 (re-export for tests)
from app.core.redis import get_shared_sync_redis_client  # noqa: F401
from app.repositories.college_repository import (
    get_by_external_id_sync as get_college_by_external_id_sync,  # noqa: F401
)
from app.repositories.crawl_run_repository import ensure_crawl_run_task_sync  # noqa: F401
from app.services.crawl.collect_sync import (
    _collect_payloads_sync,  # noqa: F401
    _get_http_status_code,  # noqa: F401
    _process_scrape_result,  # noqa: F401
    _scrape_one_sync,  # noqa: F401
    _scrape_one_sync_with_sem,  # noqa: F401
)
from app.services.crawl.entrypoints import (
    crawl_college_sync,
    handle_crawl_failure_composite,
    run_crawl_job_sync,
)
from app.services.crawl.failure import (
    CRAWL_FAILURE_REDIS_KEY_PREFIX,  # noqa: F401
    CRAWL_FAILURE_REDIS_TTL_SECONDS,  # noqa: F401
    _record_crawl_failure_fallback,  # noqa: F401
)
from app.services.crawl.pipeline_sync import (  # noqa: F401
    _DefaultSyncCrawlAdapter,
    _run_crawl_pipeline_sync,
)
from app.services.crawl.runtime import (
    CRAWL_RETRY_MAX_ATTEMPTS,  # noqa: F401 (re-export for tests)
    CrawlRuntimeConfig,  # noqa: F401
    _BoundedSeenSet,  # noqa: F401
    _cap_links_for_run,  # noqa: F401
    _crawl_retry_wait,  # noqa: F401 (re-export for tests)
    _RedisSeenSet,  # noqa: F401
)

__all__ = [
    "crawl_college_sync",
    "handle_crawl_failure_composite",
    "run_crawl_job_sync",
]
