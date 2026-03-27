"""내부 API(trigger-crawl) 도메인 계약. 서비스는 result_kind만 반환합니다."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class TriggerCrawlResultKind(str, Enum):
    """트리거 결과 종류. Router가 이 값만 보고 200/202/503을 결정."""

    cached = "cached"  # 202, Idempotency-Key 캐시 hit
    # 200: 브로커에 college별 크롤 태스크 enqueue 시도 결과.
    # 일부 college는 락 미획득으로 skipped일 수 있음(성공 종류 유지).
    success = "success"
    # 503: 최소 한 college에 대해 브로커 enqueue 실패(failed). 본문에 ALL_ENQUEUES_FAILED 등.
    partial_failure = "partial_failure"
    infra_unavailable = "infra_unavailable"  # 503, Redis 락/멱등 등 인프라 장애


@dataclass(frozen=True)
class TriggerCrawlCmd:
    """트리거 크롤 명령. college_code=None이면 전체."""

    college_code: str | None
    idempotency_key: str | None
    client_ip: str


@dataclass(frozen=True)
class TriggerCrawlResult:
    """트리거 크롤 결과. status_code 없음. Router가 result_kind로 변환."""

    result_kind: TriggerCrawlResultKind
    payload: dict[str, Any]


class CrawlDispatcherPort(Protocol):
    """크롤 태스크 enqueue 포트. 실패 시 예외 발생."""

    async def enqueue(
        self,
        college_code: str,
        lock_token: str | None,
        countdown: int,
        enqueued_at: float,
    ) -> str:
        """Enqueue 한 건. 반환 task_id. 예외 시 서비스에서 락 해제 후 failed 리스트에 추가."""
        ...
