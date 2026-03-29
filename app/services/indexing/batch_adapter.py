"""PGVector·OpenSearch 등 백엔드 교체용 배치 훅. 기본은 no-op."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol


class IndexingBatchAdapter(Protocol):
    def prepare(self, batch_context: dict[str, Any]) -> None:
        """배치 처리 전 리소스 준비."""

    @contextmanager
    def lock_context(self, batch_context: dict[str, Any]) -> Iterator[None]:
        """동시 인덱싱 가드 (DB 락·분산 락 등)."""
        ...

    def post_index(self, batch_context: dict[str, Any]) -> None:
        """벡터/보조 인덱스 반영 후 후처리."""


class NoOpIndexingBatchAdapter:
    """시맨틱 인덱스 미사용 시 파이프라인만 통과."""

    def prepare(self, batch_context: dict[str, Any]) -> None:
        return None

    @contextmanager
    def lock_context(self, batch_context: dict[str, Any]) -> Iterator[None]:
        yield

    def post_index(self, batch_context: dict[str, Any]) -> None:
        return None
