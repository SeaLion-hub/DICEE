"""공통 상수·Enum. crawl_runs.status 등 DB/API와 일치하는 값."""

from enum import Enum


class CrawlRunStatus(str, Enum):
    """CrawlRun.status 값. 마이그레이션 crawl_runs_status_check와 동일."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
