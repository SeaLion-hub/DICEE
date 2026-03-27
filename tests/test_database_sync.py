"""동기 DB 초기화 멱등성."""

from unittest.mock import MagicMock

import pytest


def test_init_sync_db_second_call_does_not_create_second_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.database_sync as ds

    ds.sync_engine = None
    ds.sync_session_factory = None

    created = {"n": 0}
    engine_mock = MagicMock()
    factory_mock = MagicMock()

    def fake_create_engine(*_a: object, **_kw: object) -> MagicMock:
        created["n"] += 1
        return engine_mock

    budget = MagicMock()
    budget.within_budget = True
    budget.app_budget = 1
    budget.message = ""

    monkeypatch.setattr(ds, "_sync_database_url", lambda: "postgresql+psycopg://u:p@127.0.0.1:5432/t")
    monkeypatch.setattr(ds, "create_engine", fake_create_engine)
    monkeypatch.setattr(ds, "sessionmaker", MagicMock(return_value=factory_mock))
    monkeypatch.setattr("app.core.database.check_pool_budget", lambda _m: budget)

    try:
        ds.init_sync_db()
        assert created["n"] == 1
        ds.init_sync_db()
        assert created["n"] == 1
        assert ds.sync_session_factory is factory_mock
    finally:
        ds.sync_engine = None
        ds.sync_session_factory = None
