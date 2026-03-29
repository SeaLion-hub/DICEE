"""IndexingBatchAdapter no-op."""

from app.services.indexing.batch_adapter import NoOpIndexingBatchAdapter


def test_noop_indexing_batch_adapter_context():
    a = NoOpIndexingBatchAdapter()
    ctx = {"batch_id": "x"}
    a.prepare(ctx)
    with a.lock_context(ctx):
        pass
    a.post_index(ctx)
