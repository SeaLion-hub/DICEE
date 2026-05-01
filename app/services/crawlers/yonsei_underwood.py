import logging
import os
import re
import urllib.parse
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag
from requests.exceptions import RequestException

from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_async,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult, require_non_empty_text, require_present
from app.services.crawlers.cms_board_view import board_view_title_from_soup
from app.services.crawlers.notice_dates import normalize_notice_date
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="underwood",
    display_name="언더우드국제대학",
    list_url="https://uic.yonsei.ac.kr/main/news.php?mid=m06_01_02",
    get_links="get_uic_links",
    scrape_detail="scrape_uic_detail",
)


def parse_uic_links_from_html(html: str, list_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, Any]] = []
    idx = 1
    for box in soup.find_all("div", class_="divbox_half_news"):
        if not isinstance(box, Tag):
            continue
        category_span = box.find("span", class_="Text_26bk")
        category = category_span.get_text(strip=True) if isinstance(category_span, Tag) else "Notice"
        newsbox = box.find("div", class_="newsbox")
        if not newsbox or not isinstance(newsbox, Tag):
            continue
        count = 0
        for a in newsbox.find_all("a"):
            if count >= 5:
                break
            if not isinstance(a, Tag):
                continue
            href = ensure_str_attr(a.get("href"))
            if not href:
                continue
            full_url = urljoin(list_url, href)
            title_hint = a.get_text(strip=True)
            if not title_hint or title_hint.lower() == "more":
                continue
            links.append({"no": str(idx), "title_hint": f"[{category}] {title_hint}", "url": full_url})
            idx += 1
            count += 1
    return links


def parse_uic_detail_from_html(html: str, detail_url: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    title = require_non_empty_text(board_view_title_from_soup(soup), field="title", url=detail_url)
    date = "날짜 없음"
    attachments: list[str] = []
    attachment_names: set[str] = set()
    for b_add in soup.find_all("div", id="BoardViewAdd"):
        if not isinstance(b_add, Tag):
            continue
        text_content = b_add.get_text(strip=True)
        if "Views:" in text_content or re.search(r"[A-Za-z]+\s+\d{1,2},\s+\d{4}", text_content):
            date = normalize_notice_date(text_content, locale="en")
        for a in b_add.find_all("a"):
            if not isinstance(a, Tag):
                continue
            if a.find("img"):
                fname = a.get_text(separator=" ", strip=True).strip('"').strip()
                fname = re.sub(r"\([\d.,]+\s*(KB|MB|GB|Bytes?)\)", "", fname, flags=re.IGNORECASE).strip()
                if fname and fname not in attachment_names:
                    attachment_names.add(fname)
                    attachments.append(fname)
    content_html = ""
    images: list[dict[str, Any]] = []
    image_urls: set[str] = set()
    content_div = soup.find("div", id="BoardContent")
    content_div = require_present(
        content_div if isinstance(content_div, Tag) else None,
        selector="div#BoardContent",
        url=detail_url,
    )
    for idx, img in enumerate(content_div.find_all("img")):
        if not isinstance(img, Tag):
            continue
        src = ensure_str_attr(img.get("src", ""))
        if src and not any(x in src for x in ["icon", "btn", "blank", "ext_"]):
            if src.startswith("data:image"):
                try:
                    header, encoded = src.split(",", 1)
                    ext = "png"
                    if "jpeg" in header or "jpg" in header:
                        ext = "jpg"
                    images.append({"type": "base64", "data": encoded, "name": f"image_{idx+1}.{ext}"})
                except Exception as e:
                    logger.warning(
                        "parse_uic_detail_from_html: failed to parse inline image (idx=%d) url=%s: %s",
                        idx,
                        detail_url,
                        e,
                    )
            else:
                full_url = urljoin(detail_url, src)
                parsed = urllib.parse.urlparse(full_url)
                encoded_path = urllib.parse.quote(parsed.path)
                safe_url = urllib.parse.urlunparse(
                    (parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment)
                )
                if safe_url not in image_urls:
                    image_urls.add(safe_url)
                    fname = os.path.basename(parsed.path)
                    images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})
        img.decompose()
    for table in content_div.find_all("table"):
        if isinstance(table, Tag) and not table.get("border"):
            table["border"] = "1"
    content_html = require_non_empty_text(content_div.decode_contents().strip(), field="content_html", url=detail_url)
    return ScrapeResult(title, date, content_html, images, attachments)


# ================================================================================
# [2] UIC 리스트 페이지 크롤링 엔진 (카테고리별 상위 5개 추출)
# ================================================================================
def get_uic_links(url):
    """UIC 메인 페이지의 divbox_half_news 박스 3개에서 각각 상위 5개의 링크를 추출합니다."""
    try:
        try:
            text = fetch_html(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_uic_links body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_uic_links_from_html(text, url)
    except RequestException:
        raise
    except Exception:
        logger.exception("get_uic_links parsing error url=%s", url)
        raise


# ================================================================================
# [3] UIC 상세 페이지 크롤링 엔진 (기존 로직 유지)
# ================================================================================
def scrape_uic_detail(url):
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_uic_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_uic_detail_from_html(text, url)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_uic_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_uic_links_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        return parse_uic_links_from_html(text, url)
    except Exception:
        logger.exception("get_uic_links_async parsing error url=%s", url)
        raise


async def scrape_uic_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        return parse_uic_detail_from_html(text, url)
    except Exception:
        logger.exception("scrape_uic_detail_async error url=%s", url)
        raise
