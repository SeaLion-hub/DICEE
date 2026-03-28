"""backfill_notice_embedding_task 멱등·입력 검증."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.core.celery_app import app as celery_app


@pytest.fixture
def celery_eager():
    prev = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = prev


def test_backfill_notice_embedding_task_invalid_uuid_returns_invalid_id(celery_eager: None) -> None:
    from app.services.tasks import backfill_notice_embedding_task

    result = backfill_notice_embedding_task.apply(args=("not-a-uuid",)).get()
    assert result == {"status": "invalid_id"}


def test_backfill_notice_embedding_task_skips_when_embedding_already_set(celery_eager: None) -> None:
    from app.constants.embeddings import EMBEDDING_DIM
    from app.services.tasks import backfill_notice_embedding_task

    nid = uuid.uuid4()
    notice = MagicMock()
    notice.embedding = [0.1] * EMBEDDING_DIM
    notice.title = "T"

    mock_session = MagicMock()

    with (
        patch("app.services.tasks.get_sync_session") as mock_cm,
        patch("app.services.tasks.get_by_id_sync", return_value=notice),
        patch("app.services.tasks.embed_text_sync") as mock_embed,
    ):
        mock_cm.return_value.__enter__.return_value = mock_session
        mock_cm.return_value.__exit__.return_value = None
        result = backfill_notice_embedding_task.apply(args=(str(nid),)).get()

    assert result == {"status": "skipped_already_set"}
    mock_embed.assert_not_called()
    mock_session.commit.assert_not_called()
