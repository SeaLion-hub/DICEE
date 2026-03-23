"""
크롤러 공통 타입 헬퍼. BeautifulSoup get("href")/get("src") 등 str | list | None → str 축소.
파일별 임시 캐스팅 대신 공통 적용해 유지보수성 확보.
"""

from collections.abc import Sequence

from bs4 import Tag


def class_list_from_tag(tag: Tag) -> list[str]:
    """태그의 class 속성을 str 목록으로 정규화한다 (mypy·런타임 안전)."""
    raw = tag.get("class")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list | tuple):
        return [str(x) for x in raw]
    return [str(raw)]


def first_element_str(seq: Sequence[str] | str | None, *, default: str = "") -> str:
    """
    시퀀스의 첫 요소를 str로 반환. BeautifulSoup 등에서 빈 결과·단일 str에 대응.
    None·빈 시퀀스면 default.
    """
    if seq is None:
        return default
    if isinstance(seq, str):
        return seq
    if len(seq) == 0:
        return default
    first = seq[0]
    return first if isinstance(first, str) else str(first)


def ensure_str_attr(attr: str | Sequence[str] | None) -> str:
    """
    BeautifulSoup 태그의 get("href")/get("src") 등 결과를 str로 반환.
    list/AttributeValueList면 첫 요소를 str로, None이면 "".
    urljoin/urlparse/set.add 등에 넘기기 전에 사용.
    """
    if attr is None:
        return ""
    if isinstance(attr, str):
        return attr
    if isinstance(attr, list | tuple) and len(attr) > 0:
        first = attr[0]
        return first if isinstance(first, str) else str(first)
    return ""
