"""연세대 화학과 공지 크롤러. SeaLion-hub/crawler chemistry.py 이식."""

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from requests.exceptions import RequestException

from app.core.bs4_utils import as_tag
from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult
from app.services.crawlers.typing_helpers import class_list_from_tag, ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="chemistry",
    display_name="화학과",
    list_url="https://chemyonsei.kr/board/notice",
    get_links="get_chemistry_links",
    scrape_detail="scrape_chemistry_detail",
)


def normalize_date(date_str: str) -> str:
    try:
        match = re.search(r"(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})", date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning("normalize_date failed: date_str=%r", date_str[:100] if date_str else None)
        return date_str


def get_chemistry_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_chemistry_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for row in soup.find_all("tr"):
            row_tag = as_tag(row)
            if row_tag is None:
                continue
            row_classes = class_list_from_tag(row_tag)
            if "nxb-list-table__notice" in row_classes:
                continue
            a_tag = row_tag.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = ensure_str_attr(a_tag.get("href"))
            if not href or href == "#" or "javascript:" in href:
                continue
            full_url = urljoin(list_url, href)
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            num_text = "일반"
            tds = row_tag.find_all("td")
            if tds:
                first_td = as_tag(tds[0])
                first_td_text = first_td.get_text(strip=True) if first_td is not None else ""
                if first_td_text.isdigit():
                    num_text = first_td_text
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                links.append({"no": num_text, "title_hint": title, "url": full_url})

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_chemistry_links parsing error list_url=%s", list_url)
        raise


def scrape_chemistry_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_chemistry_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = "제목 없음"
        title_tag = soup.find("h3", class_=lambda c: c and "nxb-view__header-title" in (c or ""))
        if title_tag and isinstance(title_tag, Tag):
            title = title_tag.get_text(strip=True)

        date = "날짜 없음"
        time_tag = soup.find("time")
        if time_tag and isinstance(time_tag, Tag):
            raw_date = ensure_str_attr(time_tag.get("datetime")) or time_tag.get_text(strip=True)
            date = normalize_date(raw_date)

        content_html = ""
        images: list[dict[str, Any]] = []
        content_div = soup.find("div", class_="editor-contents")

        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = ensure_str_attr(img.get("src"))
                if not src:
                    continue
                if src.startswith("data:image"):
                    try:
                        header, encoded = src.split(",", 1)
                        data = base64.b64decode(encoded)
                        ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
                        images.append({"type": "base64", "data": data, "name": f"image_{idx + 1}.{ext}"})
                    except Exception:
                        pass
                else:
                    full_url = urljoin(url, src)
                    parsed = urlparse(full_url)
                    if parsed.scheme not in ("http", "https"):
                        continue
                    unquoted_path = unquote(parsed.path)
                    encoded_path = quote(unquoted_path)
                    safe_url = urlunparse(
                        (
                            parsed.scheme,
                            parsed.netloc,
                            encoded_path,
                            parsed.params,
                            parsed.query,
                            parsed.fragment,
                        )
                    )
                    fname = os.path.basename(unquoted_path)
                    if not any(d.get("data") == safe_url for d in images):
                        images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx + 1}.jpg"})
                img.decompose()
            for table in content_div.find_all("table"):
                if isinstance(table, Tag) and not table.get("border"):
                    table["border"] = "1"
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        attachments: list[str] = []
        for p_tag in soup.find_all("p", class_=lambda c: c and "nxb-view__files-text" in (c or "")):
            if not isinstance(p_tag, Tag):
                continue
            for sub_tag in p_tag.find_all("sub"):
                sub_tag.decompose()
            fname = p_tag.get_text(strip=True)
            if fname and fname not in attachments:
                attachments.append(fname)

        return ScrapeResult(
            title=title,
            date_str=date,
            html_content=content_html,
            images=images,
            attachments=attachments,
        )
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_chemistry_detail error url=%s: %s", url, e)
        raise
