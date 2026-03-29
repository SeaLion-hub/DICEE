import logging
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
from app.services.crawlers.base import ScrapeResult
from app.services.crawlers.html_image_extract import extract_images_from_container
from app.services.crawlers.notice_dates import normalize_notice_date
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="glc",
    display_name="글로벌인재대학",
    list_url="https://glc.yonsei.ac.kr/notice/?mod=list",
    get_links="get_glc_links",
    scrape_detail="scrape_glc_detail",
)


def parse_glc_links_from_html(html: str, list_url: str) -> list[dict[str, Any]]:
    """목록 HTML만 파싱. I/O 없음."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, Any]] = []
    rows = soup.find_all("tr")
    for row in rows:
        if not isinstance(row, Tag):
            continue
        uid_td = row.find("td", class_="kboard-list-uid")
        if not uid_td or not isinstance(uid_td, Tag):
            continue
        uid_text = uid_td.get_text(strip=True)
        if not uid_text.isdigit():
            continue
        title_td = row.find("td", class_="kboard-list-title")
        if title_td and isinstance(title_td, Tag):
            a_tag = title_td.find("a")
            if a_tag and isinstance(a_tag, Tag):
                href_str = ensure_str_attr(a_tag.get("href"))
                if not href_str:
                    continue
                full_url = urljoin(list_url, href_str)
                title_div = a_tag.find("div", class_="kboard-default-cut-strings")
                title = title_div.get_text(strip=True) if isinstance(title_div, Tag) else a_tag.get_text(strip=True)
                links.append({"no": uid_text, "title_hint": title, "url": full_url})
    return links


def parse_glc_detail_from_html(html: str, detail_url: str) -> ScrapeResult:
    """상세 HTML만 파싱. I/O 없음."""
    soup = BeautifulSoup(html, "html.parser")
    title = "제목 없음"
    title_div = soup.find("div", class_="kboard-title")
    if title_div and isinstance(title_div, Tag):
        h1_tag = title_div.find("h1")
        if isinstance(h1_tag, Tag):
            title = h1_tag.get_text(strip=True)
    date = "날짜 없음"
    date_div = soup.find("div", class_="detail-date")
    if date_div and isinstance(date_div, Tag):
        val_div = date_div.find("div", class_="detail-value")
        if isinstance(val_div, Tag):
            date = normalize_notice_date(val_div.get_text(strip=True))
    content_html = ""
    images: list[dict[str, Any]] = []
    content_div = soup.find("div", class_="content-view")
    if content_div and isinstance(content_div, Tag):
        images = extract_images_from_container(content_div, detail_url, prefer_data_orig_src=True)
        content_html = content_div.decode_contents().strip()
    else:
        content_html = "(본문 영역을 찾을 수 없습니다)"
    attachments: list[str] = []
    attachment_names: set[str] = set()
    for btn in soup.find_all("button", class_=lambda c: bool(c and "kboard-button-download" in c)):
        if not isinstance(btn, Tag):
            continue
        fname = btn.get_text(strip=True)
        if fname and fname not in attachment_names:
            attachment_names.add(fname)
            attachments.append(fname)
    return ScrapeResult(title, date, content_html, images, attachments)


# ================================================================================
# [2] GLC 리스트 페이지 크롤링 엔진 (새로 추가됨)
# ================================================================================
def get_glc_links(url: str) -> list[dict[str, Any]]:
    """GLC 공지사항 목록에서 '공지'를 제외하고 숫자 번호를 가진 일반 글 링크만 추출합니다."""
    try:
        try:
            html = fetch_html(url)
        except HtmlTooLargeError as e:
            logger.warning("get_glc_links HTML too large: url=%s", url[:200] if url else "")
            raise RequestException from e
        return parse_glc_links_from_html(html, url)
    except RequestException:
        raise
    except Exception:
        logger.exception("get_glc_links parsing error url=%s", url)
        raise


# ================================================================================
# [3] GLC 상세 페이지 크롤링 엔진 (기존 로직 유지)
# ================================================================================
def scrape_glc_detail(url: str) -> ScrapeResult:
    try:
        try:
            html = fetch_html_detail_cached(url)
        except HtmlTooLargeError as e:
            logger.warning("scrape_glc_detail HTML too large: url=%s", url[:200] if url else "")
            raise RequestException from e
        return parse_glc_detail_from_html(html, url)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_glc_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_glc_links_async(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    try:
        html = await fetch_html_async(client, url, timeout=10.0)
        return parse_glc_links_from_html(html, url)
    except Exception:
        logger.exception("get_glc_links_async parsing error url=%s", url)
        raise


async def scrape_glc_detail_async(client: httpx.AsyncClient, url: str) -> ScrapeResult:
    try:
        html = await fetch_html_async(client, url, timeout=10.0)
        return parse_glc_detail_from_html(html, url)
    except HtmlTooLargeError as e:
        logger.warning("scrape_glc_detail_async HTML too large: url=%s", url[:200] if url else "")
        raise RequestException from e
    except Exception:
        logger.exception("scrape_glc_detail_async error url=%s", url)
        raise
