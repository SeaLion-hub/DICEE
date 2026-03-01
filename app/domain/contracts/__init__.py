"""Domain contracts (ports and input/output DTOs)."""

from app.domain.contracts.crawl_contracts import (
    AsyncNoticeRepositoryPort,
    CrawlJobFailed,
    CrawlRunRow,
    CrawlStatsQueryPort,
    NoticeDraft,
    SyncNoticeRepositoryPort,
)
from app.domain.contracts.internal_contracts import (
    CrawlDispatcherPort,
    TriggerCrawlCmd,
    TriggerCrawlResult,
    TriggerCrawlResultKind,
)
from app.domain.contracts.user_contracts import UserRecord, UserRepositoryPort, UserUpsertCmd

__all__ = [
    "AsyncNoticeRepositoryPort",
    "CrawlDispatcherPort",
    "CrawlJobFailed",
    "CrawlRunRow",
    "CrawlStatsQueryPort",
    "NoticeDraft",
    "SyncNoticeRepositoryPort",
    "TriggerCrawlCmd",
    "TriggerCrawlResult",
    "TriggerCrawlResultKind",
    "UserRecord",
    "UserRepositoryPort",
    "UserUpsertCmd",
]
