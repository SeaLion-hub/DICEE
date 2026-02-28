"""Public config interface.

Compatibility contract: external imports continue to use
`from app.core.config import settings`.
"""

from .base import Settings

settings = Settings()  # type: ignore[call-arg]


def check_pool_budget(max_conn_override: int | None = None) -> tuple[bool, int, int]:
    from app.core.database import check_pool_budget as _check_pool_budget

    effective = max_conn_override if max_conn_override is not None else settings.db.db_max_connections
    result = _check_pool_budget(effective)
    return result.within_budget, result.peak_pool_conn, result.app_budget


__all__ = ["Settings", "settings", "check_pool_budget"]
