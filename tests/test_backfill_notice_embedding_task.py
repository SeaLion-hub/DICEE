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


def test_backfill_notice_embedding_task_embeds_after_read_session_closes(celery_eager: None) -> None:
    from app.constants.embeddings import EMBEDDING_DIM
    from app.services.tasks import backfill_notice_embedding_task

    nid = uuid.uuid4()
    notice = MagicMock()
    notice.embedding = None
    notice.title = "Title"
    events: list[str] = []

    read_cm = MagicMock()
    read_session = MagicMock()
    read_cm.__enter__.side_effect = lambda: events.append("read_enter") or read_session
    read_cm.__exit__.side_effect = lambda *_args: events.append("read_exit") or None

    write_cm = MagicMock()
    write_session = MagicMock()
    write_cm.__enter__.side_effect = lambda: events.append("write_enter") or write_session
    write_cm.__exit__.side_effect = lambda *_args: events.append("write_exit") or None

    def _embed(_title: str) -> list[float]:
        events.append("embed")
        return [0.1] * EMBEDDING_DIM

    with (
        patch("app.services.tasks.get_sync_session", side_effect=[read_cm, write_cm]),
        patch("app.services.tasks.get_by_id_sync", return_value=notice),
        patch("app.services.tasks.embed_text_sync", side_effect=_embed),
        patch("app.services.tasks.update_notice_embedding_if_missing_sync", return_value=True) as mock_update,
    ):
        result = backfill_notice_embedding_task.apply(args=(str(nid),)).get()

    assert result == {"status": "ok"}
    assert events == ["read_enter", "read_exit", "embed", "write_enter", "write_exit"]
    mock_update.assert_called_once_with(write_session, nid, [0.1] * EMBEDDING_DIM)


def test_backfill_notice_embedding_task_does_not_overwrite_racing_embedding(celery_eager: None) -> None:
    from app.constants.embeddings import EMBEDDING_DIM
    from app.services.tasks import backfill_notice_embedding_task

    nid = uuid.uuid4()
    notice = MagicMock()
    notice.embedding = None
    notice.title = "Title"

    cm = MagicMock()
    cm.__enter__.return_value = MagicMock()
    cm.__exit__.return_value = None

    with (
        patch("app.services.tasks.get_sync_session", side_effect=[cm, cm]),
        patch("app.services.tasks.get_by_id_sync", return_value=notice),
        patch("app.services.tasks.embed_text_sync", return_value=[0.1] * EMBEDDING_DIM),
        patch("app.services.tasks.update_notice_embedding_if_missing_sync", return_value=False),
    ):
        result = backfill_notice_embedding_task.apply(args=(str(nid),)).get()

    assert result == {"status": "skipped_already_set"}
