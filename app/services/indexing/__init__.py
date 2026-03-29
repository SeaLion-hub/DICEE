"""인덱싱 어댑터 (벡터·하이브리드 검색 교체 지점)."""

from app.services.indexing.batch_adapter import IndexingBatchAdapter, NoOpIndexingBatchAdapter

__all__ = ["IndexingBatchAdapter", "NoOpIndexingBatchAdapter"]
