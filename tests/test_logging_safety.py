"""ProductionExceptionFilter: production에서 exc_info 스택 누출 차단."""

import logging

import pytest
from app.core.logging_safety import ProductionExceptionFilter


def test_production_filter_strips_exc_info_and_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.logging_safety.settings", type("S", (), {"environment": "production"})())

    flt = ProductionExceptionFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="x",
        lineno=1,
        msg="secret %s",
        args=("detail",),
        exc_info=(ValueError, ValueError("boom"), None),
    )
    assert flt.filter(record) is True
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.msg == "Internal error (ValueError)"
    assert record.args == ()


def test_production_filter_unknown_exc_type_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.logging_safety.settings", type("S", (), {"environment": "production"})())

    flt = ProductionExceptionFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="x",
        lineno=1,
        msg="x",
        args=(),
        exc_info=(None, None, None),
    )
    assert flt.filter(record) is True
    assert record.msg == "Internal error (Unknown)"


def test_non_production_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.logging_safety.settings", type("S", (), {"environment": "development"})())

    flt = ProductionExceptionFilter()
    exc = ValueError("keep")
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="x",
        lineno=1,
        msg="err",
        args=(),
        exc_info=(ValueError, exc, None),
    )
    assert flt.filter(record) is True
    assert record.exc_info is not None
    assert record.msg == "err"
