"""Helpers for Alembic runtime behavior."""

from __future__ import annotations

import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection


def acquire_migration_lock(
    connection: Connection,
    lock_id: int,
    *,
    lock_wait_sec: float,
    lock_retries: int,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Acquire a session-level advisory lock and clear SQLAlchemy's autobegin state.

    SQLAlchemy 2 starts a transaction on the first SELECT. Alembic treats an
    already-open transaction as "external" and skips its own commit handling, so
    the migration can be rolled back on connection close unless we commit first.
    The advisory lock survives commit because it is session-scoped.
    """

    def _try_lock() -> bool:
        return bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lid)"),
                {"lid": lock_id},
            ).scalar()
        )

    lock_acquired = _try_lock()
    if not lock_acquired:
        for _ in range(lock_retries):
            sleep(lock_wait_sec)
            lock_acquired = _try_lock()
            if lock_acquired:
                break

    if lock_acquired and connection.in_transaction():
        connection.commit()

    return lock_acquired
