"""alembic runtime helpers: advisory lock and transaction reset behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.alembic_runtime import acquire_migration_lock


def _scalar_result(value: bool) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    return result


def test_acquire_migration_lock_commits_autobegun_transaction() -> None:
    connection = MagicMock()
    connection.execute.return_value = _scalar_result(True)
    connection.in_transaction.return_value = True

    acquired = acquire_migration_lock(
        connection,
        123,
        lock_wait_sec=0.1,
        lock_retries=0,
        sleep=lambda _sec: None,
    )

    assert acquired is True
    connection.commit.assert_called_once()


def test_acquire_migration_lock_retries_until_available() -> None:
    connection = MagicMock()
    connection.execute.side_effect = [
        _scalar_result(False),
        _scalar_result(False),
        _scalar_result(True),
    ]
    connection.in_transaction.return_value = True
    slept: list[float] = []

    acquired = acquire_migration_lock(
        connection,
        123,
        lock_wait_sec=0.25,
        lock_retries=2,
        sleep=slept.append,
    )

    assert acquired is True
    assert slept == [0.25, 0.25]
    connection.commit.assert_called_once()


def test_acquire_migration_lock_returns_false_without_commit_when_unavailable() -> None:
    connection = MagicMock()
    connection.execute.side_effect = [
        _scalar_result(False),
        _scalar_result(False),
        _scalar_result(False),
    ]

    acquired = acquire_migration_lock(
        connection,
        123,
        lock_wait_sec=0.25,
        lock_retries=2,
        sleep=lambda _sec: None,
    )

    assert acquired is False
    connection.commit.assert_not_called()
