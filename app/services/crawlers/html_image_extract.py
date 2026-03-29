"""본문 컨테이너에서 이미지 추출·img 제거·table border 보정."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import Tag

from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

_DEFAULT_ICON_SUBSTRINGS = ("icon", "btn", "blank")


def extract_images_from_container(
    content_div: Tag,
    page_url: str,
    *,
    prefer_data_orig_src: bool = False,
    icon_substrings: tuple[str, ...] = _DEFAULT_ICON_SUBSTRINGS,
    dedupe_by_data_url: bool = True,
) -> list[dict[str, Any]]:
    """
    content_div 내부 img를 순회해 images 리스트를 만들고 각 img는 decompose한다.
    http(s) URL은 path 인코딩 정규화. base64는 type base64, data는 ASCII 문자열.

    dedupe_by_data_url=True: 동일 safe_url이 이미 있으면 스킵 (기존 chemistry/GLC 패턴).
    """
    images: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for idx, img in enumerate(content_div.find_all("img")):
        if not isinstance(img, Tag):
            continue
        raw_src = img.get("data-orig-src") if prefer_data_orig_src else None
        if not raw_src:
            raw_src = img.get("src", "")
        src = raw_src if isinstance(raw_src, str) else ensure_str_attr(raw_src)
        if not src:
            continue
        if icon_substrings and any(x in src for x in icon_substrings):
            img.decompose()
            continue

        if src.startswith("data:image"):
            try:
                header, encoded = src.split(",", 1)
                ext = "png"
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                try:
                    base64.b64decode(encoded, validate=True)
                except Exception:
                    img.decompose()
                    continue
                images.append({"type": "base64", "data": encoded, "name": f"image_{idx + 1}.{ext}"})
            except Exception:
                logger.debug("base64 image split failed idx=%s", idx, exc_info=True)
        else:
            full_url = urljoin(page_url, src)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                img.decompose()
                continue
            unquoted_path = unquote(parsed.path)
            encoded_path = quote(unquoted_path)
            safe_url = urlunparse(
                (parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment)
            )
            fname = os.path.basename(unquoted_path)
            if dedupe_by_data_url and safe_url in seen_urls:
                img.decompose()
                continue
            seen_urls.add(safe_url)
            images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx + 1}.jpg"})

        img.decompose()

    for table in content_div.find_all("table"):
        if isinstance(table, Tag) and not table.get("border"):
            table["border"] = "1"

    return images
