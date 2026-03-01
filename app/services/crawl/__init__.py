# Crawl package: runtime, collect_sync, pipeline_sync, failure, entrypoints.
# Public API: use app.services.crawl.entrypoints or app.services.crawl_service (re-export).

from app.services.crawl.entrypoints import (
    crawl_college_sync,
    handle_crawl_failure_composite,
    run_crawl_job_sync,
)

__all__ = [
    "crawl_college_sync",
    "handle_crawl_failure_composite",
    "run_crawl_job_sync",
]
