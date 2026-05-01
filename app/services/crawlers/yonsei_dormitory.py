"""연세대 생활관 공지 크롤러. SeaLion-hub/crawler dormitory.py 이식."""

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from requests.exceptions import RequestException

from app.core.bs4_utils import as_tag
from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult, require_non_empty_text, require_present
from app.services.crawlers.link_dedupe import dedupe_link_dicts_by_url
from app.services.crawlers.notice_dates import normalize_notice_date
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="dormitory",
    display_name="생활관",
    list_url="https://dorm.yonsei.ac.kr/board/?id=notice&p=1",
    get_links="get_dormitory_links",
    scrape_detail="scrape_dormitory_detail",
)


def get_dormitory_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_dormitory_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []

        for row in soup.find_all("tr"):
            row_tag = as_tag(row)
            if row_tag is None:
                continue
            title_td = row_tag.find("td", class_=lambda c: bool(c and "bold" in (c or "")))
            if not title_td or not isinstance(title_td, Tag):
                continue
            a_tag = title_td.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = ensure_str_attr(a_tag.get("href"))
            if not href or href == "#" or "javascript:" in href:
                continue
            full_url = urljoin(list_url, href)
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            num_text = "공지"
            tds = row_tag.find_all("td")
            if tds:
                first_td_text = tds[0].get_text(strip=True) if isinstance(tds[0], Tag) else ""
                if first_td_text.isdigit():
                    num_text = first_td_text
            links.append({"no": num_text, "title_hint": title, "url": full_url})

        return dedupe_link_dicts_by_url(links)
    except RequestException:
        raise
    except Exception:
        logger.exception("get_dormitory_links parsing error list_url=%s", list_url)
        raise


def scrape_dormitory_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_dormitory_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = ""
        title_h3 = soup.find("h3", class_="title")
        if title_h3 and isinstance(title_h3, Tag):
            title = title_h3.get_text(strip=True)
        title = require_non_empty_text(title, field="title", url=url)

        date = "날짜 없음"
        info_div = soup.find("div", class_="board-view-info")
        if info_div and isinstance(info_div, Tag):
            info_text = info_div.get_text(separator=" ", strip=True)
            date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", info_text)
            if date_match:
                date = normalize_notice_date(date_match.group())

        content_html = ""
        images: list[dict[str, Any]] = []
        content_div = soup.find("div", class_="board-view-data")
        content_div = require_present(
            content_div if isinstance(content_div, Tag) else None,
            selector="div.board-view-data",
            url=url,
        )

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
                fname = ensure_str_attr(img.get("title")) or os.path.basename(unquoted_path)
                if not any(d.get("data") == safe_url for d in images):
                    images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx + 1}.jpg"})
            img.decompose()
        for table in content_div.find_all("table"):
            if isinstance(table, Tag) and not table.get("border"):
                table["border"] = "1"
        content_html = require_non_empty_text(content_div.decode_contents().strip(), field="content_html", url=url)

        attachments: list[str] = []
        for p_tag in soup.find_all("p", class_="file"):
            if not isinstance(p_tag, Tag):
                continue
            span_tag = p_tag.find("span")
            if span_tag and isinstance(span_tag, Tag):
                fname = "".join(node for node in span_tag.contents if isinstance(node, NavigableString)).strip()
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
        logger.exception("scrape_dormitory_detail error url=%s: %s", url, e)
        raise
