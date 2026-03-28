"""
Property-based tests for crawl_payload parsing utilities (Hypothesis).

대상:
- _external_id_from_url: 임의 문자열 URL 입력 시 예외 없이 비어 있지 않은 str 반환.
- _parse_published_at: 임의 문자열·None 입력 시 예외 없음; 성공 시 UTC·실제 달력 날짜.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from app.services.crawl_payload import _external_id_from_url, _parse_published_at
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite


@pytest.fixture(autouse=True)
def _noop_crawl_sentry() -> None:
    """파싱 실패 분기에서 Sentry/로깅 부가 효과만 막고 프로덕션 로직은 그대로 둔다."""
    with (
        patch("app.services.crawl_payload._capture_crawl_sentry_exception"),
        patch("app.services.crawl_payload._capture_crawl_sentry_message"),
    ):
        yield


@composite
def _invalid_calendar_ymd(draw) -> tuple[int, int, int]:
    """항상 달력에 없는 (연, 월, 일)."""
    choice = draw(st.integers(0, 2))
    y = draw(st.integers(1970, 9999))
    if choice == 0:
        return (y, 2, 30)
    if choice == 1:
        assume(not calendar.isleap(y))
        return (y, 2, 29)
    m = draw(st.sampled_from((4, 6, 9, 11)))
    return (y, m, 31)


@settings(max_examples=100)
@given(url=st.text(max_size=4096))
def test_external_id_from_url_never_raises_nonempty_str(url: str) -> None:
    """임의(유니코드·빈 문자열·긴 문자열) 입력에서도 크래시 없이 str을 반환한다."""
    out = _external_id_from_url(url)
    assert isinstance(out, str)
    assert len(out) > 0


@settings(max_examples=100)
@given(
    st.one_of(
        st.none(),
        st.text(max_size=2048),
    )
)
def test_parse_published_at_never_raises(date_str: str | None) -> None:
    """None·임의 텍스트에서 예외 없이 None 또는 datetime만 반환."""
    out = _parse_published_at(date_str)
    assert out is None or isinstance(out, datetime)
    if isinstance(out, datetime):
        assert out.tzinfo is UTC


@settings(max_examples=100)
@given(
    d=st.dates(min_value=date(1970, 1, 1), max_value=date(9999, 12, 31)),
    sep=st.sampled_from([".", "-"]),
    pad_m=st.booleans(),
    pad_d=st.booleans(),
)
def test_parse_published_at_embedded_valid_calendar_date(
    d: date,
    sep: str,
    pad_m: bool,
    pad_d: bool,
) -> None:
    """정규식이 잡는 YYYYsepMMsepDD가 본문에 있으면 해당 달력 날짜로 파싱된다."""
    m_s = f"{d.month:02d}" if pad_m else str(d.month)
    d_s = f"{d.day:02d}" if pad_d else str(d.day)
    inner = f"{d.year}{sep}{m_s}{sep}{d_s}"
    date_str = f"게시 {inner} 추가텍스트"
    out = _parse_published_at(date_str)
    assert out is not None
    assert out.tzinfo is UTC
    assert out.year == d.year
    assert out.month == d.month
    assert out.day == d.day


@settings(max_examples=100)
@given(_invalid_calendar_ymd())
def test_parse_published_at_regex_but_invalid_calendar_returns_none(
    ymd: tuple[int, int, int],
) -> None:
    """YYYY-MM-DD 형태로 정규식에 걸리지만 달력상 없는 날짜면 None."""
    y, m, d = ymd
    s = f"{y:04d}-{m:02d}-{d:02d}"
    out = _parse_published_at(s)
    assert out is None
