"""calendar_service 구간 파싱."""

import pytest
from app.services.calendar_service import CalendarRangeError, parse_calendar_range


def test_month_range_march_2026() -> None:
    r = parse_calendar_range(year=2026, month=3, date_from=None, date_to=None)
    assert r.start < r.end
    delta_days = (r.end - r.start).total_seconds() / 86400
    assert 28 <= delta_days <= 32


def test_range_mode_priority_over_month() -> None:
    r = parse_calendar_range(year=2026, month=3, date_from="2026-03-10", date_to="2026-03-20")
    assert r.start < r.end
    delta_days = (r.end - r.start).total_seconds() / 86400
    assert 9 <= delta_days <= 11


def test_range_requires_both() -> None:
    with pytest.raises(CalendarRangeError):
        parse_calendar_range(year=None, month=None, date_from="2026-01-01", date_to=None)


def test_range_from_ge_to_raises() -> None:
    with pytest.raises(CalendarRangeError):
        parse_calendar_range(
            year=None,
            month=None,
            date_from="2026-02-10",
            date_to="2026-02-01",
        )


def test_month_requires_both() -> None:
    with pytest.raises(CalendarRangeError):
        parse_calendar_range(year=2026, month=None, date_from=None, date_to=None)
