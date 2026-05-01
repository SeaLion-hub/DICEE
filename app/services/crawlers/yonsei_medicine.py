import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Comment, Tag
from bs4.element import PageElement
from requests.exceptions import RequestException

from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_async,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult, require_non_empty_text, require_present
from app.services.crawlers.notice_dates import normalize_notice_date_split_tokens
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="medicine",
    display_name="의과대학",
    list_url="https://medicine.yonsei.ac.kr/medicine/news/notice.do",
    get_links="get_medicine_notice_links",
    scrape_detail="scrape_medicine_detail",
)

# ==============================================================================
# [1] 유틸리티 함수
# ==============================================================================


def clean_html_content(element: Tag) -> str:
    """HTML 본문 정제 (스크립트 제거, 표 보존). 원본 보호를 위해 문자열로 깊은 복사."""
    element_copy = BeautifulSoup(str(element), "html.parser")

    # 보안상 제거
    for tag in element_copy.find_all(["script", "style", "noscript", "iframe", "img"]):
        tag.decompose()

    # 표 테두리 강제 적용
    for table in element_copy.find_all("table"):
        if not isinstance(table, Tag):
            continue
        if not table.get("border"):
            table["border"] = "1"

    return element_copy.decode_contents().strip()


def parse_medicine_notice_links_from_html(html: str, list_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, Any]] = []
    items = [t for t in soup.find_all("div", class_="bbs-item") if isinstance(t, Tag)]
    if not items:
        fallback = soup.select(".bbs-list li") or soup.select("tbody tr")
        items = [t for t in fallback if isinstance(t, Tag)]
    seen_urls: set[str] = set()
    for item in items:
        if not isinstance(item, Tag):
            continue
        a_tag = item.find("a")
        if not a_tag or not isinstance(a_tag, Tag):
            continue
        href = ensure_str_attr(a_tag.get("href", ""))
        if "articleNo" not in href and "mode=view" not in href:
            continue
        full_url = urljoin(list_url, href)
        no_text = None
        try:
            q = parse_qs(urlparse(full_url).query)
            for key in ("articleNo", "article_no", "no", "id"):
                if q.get(key):
                    no_text = str(q[key][0])
                    break
        except Exception as e:
            logger.warning(
                "parse_medicine_notice_links_from_html: failed to parse query params for url=%s: %s",
                full_url,
                e,
            )
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            links.append({"url": full_url, "no": no_text if no_text else "Post"})
    return links


def parse_medicine_detail_from_html(html: str, detail_url: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    header = soup.find(class_="article-header")
    header = require_present(header if isinstance(header, Tag) else None, selector=".article-header", url=detail_url)
    if isinstance(header, Tag):
        t_tag = header.find(["h1", "h2", "h3", "h4"])
        if t_tag is not None and isinstance(t_tag, Tag):
            title = t_tag.get_text(strip=True)
        else:
            title = header.get_text(strip=True)
    date = "날짜 없음"
    title = require_non_empty_text(title, field="title", url=detail_url)
    d_text = header.get_text() if isinstance(header, Tag) else soup.get_text()
    d_match = re.search(r"\d{4}[.-]\s*\d{1,2}[.-]\s*\d{1,2}", d_text)
    if d_match:
        date = normalize_notice_date_split_tokens(d_match.group())
    content_html = ""
    fr_view = soup.find("div", class_="fr-view")
    fr_view = require_present(fr_view if isinstance(fr_view, Tag) else None, selector="div.fr-view", url=detail_url)
    end_comment = fr_view.find(string=lambda t: isinstance(t, Comment) and "키워드/태그" in t)
    if end_comment:
        curr: PageElement | None = end_comment
        while curr:
            nxt = curr.next_sibling
            curr.extract()
            curr = nxt
    content_html = clean_html_content(fr_view)
    content_html = require_non_empty_text(content_html, field="content_html", url=detail_url)
    images: list[dict[str, Any]] = []
    image_urls: set[str] = set()
    raw_view = soup.find("div", class_="fr-view")
    if raw_view and isinstance(raw_view, Tag):
        for img in raw_view.find_all("img"):
            if not isinstance(img, Tag):
                continue
            src = ensure_str_attr(img.get("src", ""))
            if not src:
                continue
            if src.startswith("data:image"):
                try:
                    head, enc = src.split(",", 1)
                    ext = "png"
                    if "jpeg" in head:
                        ext = "jpg"
                    images.append({"type": "base64", "data": enc, "name": f"img.{ext}"})
                except Exception as e:
                    logger.warning(
                        "parse_medicine_detail_from_html: failed to parse inline image url=%s: %s",
                        detail_url,
                        e,
                    )
                    continue
            else:
                if any(x in src for x in ["icon", "btn", "blank"]):
                    continue
                full_url = urljoin(detail_url, src)
                if full_url not in image_urls:
                    image_urls.add(full_url)
                    fname = os.path.basename(full_url.split("?")[0])
                    if not fname or "." not in fname:
                        fname = "image.jpg"
                    images.append({"type": "url", "data": full_url, "name": fname})
    attachments: list[str] = []
    attachment_names: set[str] = set()
    attach_div = soup.find("div", class_="attach-files")
    if attach_div and isinstance(attach_div, Tag):
        for a in attach_div.find_all("a"):
            if not isinstance(a, Tag):
                continue
            href = ensure_str_attr(a.get("href", ""))
            if "download" in href or "mode=download" in href:
                fname = a.get_text(strip=True)
                if fname and fname not in attachment_names:
                    attachment_names.add(fname)
                    attachments.append(fname)
    return ScrapeResult(title, date, content_html, images, attachments)


# ==============================================================================
# [2] 목록 수집 엔진 (List Crawler) - 수정됨
# ==============================================================================


def get_medicine_notice_links(list_url):
    """
    게시판 목록에서 'bbs-item' 클래스를 가진 요소들의 링크를 수집합니다.
    (페이지네이션 버튼 전까지만 수집하는 효과)
    """
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_medicine_notice_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_medicine_notice_links_from_html(text, list_url)
    except RequestException:
        raise
    except Exception:
        logger.exception("get_medicine_notice_links parsing error list_url=%s", list_url)
        raise


# ==============================================================================
# [3] 상세 페이지 수집 엔진 (Detail Crawler) - 기존 유지
# ==============================================================================


def scrape_medicine_detail(url):
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_medicine_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_medicine_detail_from_html(text, url)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_medicine_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_medicine_notice_links_async(client: httpx.AsyncClient, list_url: str):
    try:
        text = await fetch_html_async(client, list_url, timeout=10.0)
        return parse_medicine_notice_links_from_html(text, list_url)
    except Exception:
        logger.exception("get_medicine_notice_links_async parsing error list_url=%s", list_url)
        raise


async def scrape_medicine_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        return parse_medicine_detail_from_html(text, url)
    except Exception:
        logger.exception("scrape_medicine_detail_async error url=%s", url)
        raise
