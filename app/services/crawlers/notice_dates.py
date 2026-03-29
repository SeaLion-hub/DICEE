"""공지 날짜 문자열 정규화. 크롤러 모듈별 복붙 제거."""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

_EN_MONTHS = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}

_KR_DATE_RE = re.compile(r"(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})")
_EN_MONTH_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")


def _normalize_english_month_date(date_str: str) -> str | None:
    m = _EN_MONTH_RE.search(date_str)
    if not m:
        return None
    m_str, d_str, y_str = m.groups()
    m_num = _EN_MONTHS.get(m_str[:3].capitalize(), "01")
    return f"{y_str}.{m_num}.{d_str.zfill(2)}"


def _normalize_korean_style_date(date_str: str) -> str | None:
    m = _KR_DATE_RE.search(date_str)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}.{mo.zfill(2)}.{d.zfill(2)}"


def _loose_digit_fallback(date_str: str) -> str | None:
    """경영대 등 연속 숫자 토큰 기반 파싱 (기존 yonsei_business.normalize_date 동작)."""
    try:
        numbers = re.findall(r"\d+", date_str)
        if len(numbers) < 3:
            return None
        y, m, d = numbers[:3]
        if len(y) == 2:
            y = "20" + y
        return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
    except Exception:
        return None


def normalize_notice_date_split_tokens(date_str: str) -> str:
    """년/월/일·슬래시·하이픈을 점으로 바꾼 뒤 숫자 토큰 3개 추출 (의과대·인공지능융합대 등)."""
    if not date_str or not isinstance(date_str, str):
        return date_str if isinstance(date_str, str) else ""
    try:
        clean = re.sub(r"[년월일/-]", ".", date_str)
        parts = [p.strip() for p in clean.split(".") if p.strip().isdigit()]
        if len(parts) >= 3:
            y, m, d = parts[:3]
            if len(y) == 2:
                y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning(
            "normalize_notice_date_split_tokens failed: date_str=%r",
            date_str[:100] if date_str else None,
        )
        return date_str


def normalize_notice_date(
    date_str: str,
    *,
    locale: Literal["ko", "en"] = "ko",
    loose_digit_fallback: bool = False,
) -> str:
    """
    날짜 문자열을 YYYY.MM.DD 형태로 맞춘다. 매칭 실패 시 원문 반환.

    locale=en: 언더우드 등 영문 월(Mon DD, YYYY) 후 한국식 패턴.
    locale=ko: 한국식 패턴 우선; loose_digit_fallback=True이면 숫자 나열 폴백.
    """
    if not date_str or not isinstance(date_str, str):
        return date_str if isinstance(date_str, str) else ""
    try:
        if locale == "en":
            en = _normalize_english_month_date(date_str)
            if en:
                return en
        kr = _normalize_korean_style_date(date_str)
        if kr:
            return kr
        if loose_digit_fallback:
            loose = _loose_digit_fallback(date_str)
            if loose:
                return loose
        return date_str
    except Exception:
        logger.warning(
            "normalize_notice_date failed (format change?): date_str=%r",
            date_str[:100] if date_str else None,
        )
        return date_str
