"""연세대 창업지원단 공지 크롤러. SeaLion-hub/crawler startup.py 이식."""

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
    college_code="startup",
    display_name="창업지원단",
    list_url="https://venture.yonsei.ac.kr/community/notice",
    get_links="get_startup_links",
    scrape_detail="scrape_startup_detail",
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


def get_startup_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_startup_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []

        for row in soup.find_all("tr"):
            row_tag = as_tag(row)
            if row_tag is None:
                continue
            row_classes = class_list_from_tag(row_tag)
            if "covi-post__notice" in row_classes:
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
            if tds and isinstance(tds[0], Tag):
                first_td_text = tds[0].get_text(strip=True)
                if first_td_text.isdigit():
                    num_text = first_td_text
            if not any(d["url"] == full_url for d in links):
                links.append({"no": num_text, "title_hint": title, "url": full_url})

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_startup_links parsing error list_url=%s", list_url)
        raise


def scrape_startup_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_startup_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = "제목 없음"
        title_tag = soup.find("h4", class_="covi-post-view__header-title")
        if title_tag and isinstance(title_tag, Tag):
            title = title_tag.get_text(strip=True)

        date = "날짜 없음"
        info_div = soup.find("div", class_="covi-post-view__header-text")
        if info_div and isinstance(info_div, Tag):
            date_p = info_div.find("p", attrs={"datetime": True})
            if date_p and isinstance(date_p, Tag) and date_p.get("datetime"):
                date = normalize_date(str(date_p["datetime"]))
            else:
                info_text = info_div.get_text(separator=" ", strip=True)
                date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", info_text)
                if date_match:
                    date = normalize_date(date_match.group())

        content_html = ""
        images: list[dict[str, Any]] = []
        content_section = soup.find("section", class_="covi-post-view__contents")

        if content_section and isinstance(content_section, Tag):
            for idx, img in enumerate(content_section.find_all("img")):
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
            for table in content_section.find_all("table"):
                if isinstance(table, Tag) and not table.get("border"):
                    table["border"] = "1"
            content_html = content_section.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        attachments: list[str] = []
        files_container = soup.find("div", class_="covi-post-view__files-container")
        if files_container and isinstance(files_container, Tag):
            for name_span in files_container.find_all("span", class_="covi-post-view__files-name"):
                if not isinstance(name_span, Tag):
                    continue
                fname = name_span.get_text(strip=True)
                ext_span = name_span.find_next_sibling("span", class_="covi-post-view__files-ext")
                if ext_span and isinstance(ext_span, Tag):
                    fname += ext_span.get_text(strip=True)
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
        logger.exception("scrape_startup_detail error url=%s: %s", url, e)
        raise
