"""
크롤러 공통 타입 헬퍼. BeautifulSoup get("href")/get("src") 등 str | list | None → str 축소.
파일별 임시 캐스팅 대신 공통 적용해 유지보수성 확보.
"""

from collections.abc import Sequence


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
