"""Celery task_failure 시그널 핸들러(메트릭·로그)."""

from app.core.celery_app import _on_celery_task_failure
from app.core.metrics import CELERY_TASK_FAILURE_TOTAL, get_counter


def test_celery_task_failure_handler_increments_metric() -> None:
    class FakeSender:
        name = "app.services.tasks.some_task"

    labels = {"task": FakeSender.name}
    before = get_counter(CELERY_TASK_FAILURE_TOTAL, labels=labels)
    _on_celery_task_failure(sender=FakeSender(), task_id="task-uuid", exception=ValueError("boom"))
    after = get_counter(CELERY_TASK_FAILURE_TOTAL, labels=labels)
    assert after == before + 1
