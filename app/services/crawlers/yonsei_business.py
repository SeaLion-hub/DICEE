import logging
import os
import re
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
from app.services.crawlers.fetch_config import BUSINESS_SITE_FETCH
from app.services.crawlers.link_dedupe import dedupe_link_dicts_by_url
from app.services.crawlers.notice_dates import normalize_notice_date
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="business",
    display_name="경영대학",
    list_url="https://ysb.yonsei.ac.kr/board.asp?mid=m06_01",
    get_links="get_business_notice_links",
    scrape_detail="scrape_business_detail",
)

# ==============================================================================
# [1] 유틸리티 함수
# ==============================================================================


def clean_html_content(element: Tag) -> str:
    """HTML 본문 정제 (스크립트 제거, 표 보존, 하단 버튼 제거). 원본 보호를 위해 문자열로 깊은 복사."""
    element_copy = BeautifulSoup(str(element), "html.parser")

    # 보안상 제거
    for tag in element_copy.find_all(["script", "style", "noscript", "iframe", "img"]):
        tag.decompose()

    # 하단 목록/수정 버튼 영역 제거
    for tag in element_copy.find_all(id="boardicon"):
        tag.decompose()

    # 표 테두리 강제 적용
    for table in element_copy.find_all("table"):
        if not isinstance(table, Tag):
            continue
        if not table.get("border"):
            table["border"] = "1"

    return element_copy.decode_contents().strip()


# ==============================================================================
# [2] 목록 수집 엔진 (List Crawler)
# ==============================================================================


def get_business_notice_links(list_url):
    """
    경영대 게시판에서 <td class="Subject"> 내부의 링크만 수집
    """
    try:
        try:
            text = fetch_html(
                list_url,
                timeout=BUSINESS_SITE_FETCH.list_timeout_seconds,
                encoding=BUSINESS_SITE_FETCH.list_encoding,
                request_meta=BUSINESS_SITE_FETCH.list_request_meta,
            )
        except HtmlTooLargeError as e:
            logger.warning("get_business_notice_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        # 1. <td class="Subject"> 찾기
        subjects = soup.find_all("td", class_="Subject")

        if not subjects:
            # 대소문자 문제일 수 있으므로 소문자로도 시도
            subjects = soup.find_all("td", class_="subject")

        for td in subjects:
            if not isinstance(td, Tag):
                continue
            # 2. 링크(a) 태그 추출
            a_tag = td.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue

            href = ensure_str_attr(a_tag.get("href", ""))
            title_text = a_tag.get_text(strip=True)

            if href:
                full_url = urljoin(list_url, href)

                # 번호 추출 (Subject 바로 앞 td가 보통 번호임)
                # 이전 형제 태그 찾기
                prev_td = td.find_previous_sibling("td")
                no_text = ""
                if prev_td and isinstance(prev_td, Tag):
                    no_text = prev_td.get_text(strip=True)

                # ★ 숫자가 아닌 경우(예: '공지', 'Link' 등) 빈 문자열로 처리하여
                # _external_id_from_url이 url에서 idx를 파싱하도록 유도
                if not no_text.isdigit():
                    no_text = ""

                # 중복 방지 (set 기반 O(1))
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    links.append(
                        {
                            "no": no_text,
                            "url": full_url,
                            "title_hint": title_text,  # 디버깅용
                        }
                    )

        return links

    except RequestException:
        raise
    except Exception:
        logger.exception("get_business_notice_links parsing error list_url=%s", list_url)
        raise


# ==============================================================================
# [3] 상세 페이지 수집 엔진 (Detail Crawler) - app5.py 로직 계승
# ==============================================================================


def parse_business_detail_from_html(html: str, url: str) -> ScrapeResult:
    """상세 HTML만 파싱. I/O 없음."""
    soup = BeautifulSoup(html, "html.parser")
    title = require_non_empty_text(board_view_title_from_soup(soup), field="title", url=url)

    date = "날짜 없음"
    info = soup.find(id="BoardViewAdd")
    if isinstance(info, Tag):
        txt = info.get_text()
        match = re.search(r"등록일\s*:\s*([\d.-]+)", txt)
        if match:
            date = normalize_notice_date(match.group(1), loose_digit_fallback=True)
        else:
            m2 = re.search(r"\d{4}[.-]\d{2}[.-]\d{2}", txt)
            if m2:
                date = normalize_notice_date(m2.group(), loose_digit_fallback=True)

    content_html = ""
    container = soup.find("div", id="BoardContent")
    container = require_present(container if isinstance(container, Tag) else None, selector="div#BoardContent", url=url)
    content_html = require_non_empty_text(clean_html_content(container), field="content_html", url=url)

    images: list[dict[str, Any]] = []
    image_urls: set[str] = set()
    raw_cont = soup.find("div", id="BoardContent")
    if raw_cont and isinstance(raw_cont, Tag):
        for img in raw_cont.find_all("img"):
            if not isinstance(img, Tag):
                continue
            img_src = ensure_str_attr(img.get("src", ""))
            if not img_src:
                continue
            if img_src.startswith("data:image"):
                try:
                    _header, enc = img_src.split(",", 1)
                    images.append({"type": "base64", "data": enc, "name": "img.png"})
                except Exception:
                    continue
            else:
                if any(x in img_src for x in ["icon", "btn", "blank"]):
                    continue
                full_url_str = urljoin(url, img_src)
                fname = os.path.basename(full_url_str.split("?")[0])
                if not fname or "." not in fname:
                    fname = "image.jpg"
                if full_url_str not in image_urls:
                    image_urls.add(full_url_str)
                    images.append({"type": "url", "data": full_url_str, "name": fname})

    attachments: list[str] = []
    attachment_names_set: set[str] = set()
    area = soup.find(id="BoardViewFile")
    file_container = area if (area is not None and isinstance(area, Tag)) else soup
    for a in file_container.find_all("a"):
        if not isinstance(a, Tag):
            continue
        raw_href = a.get("href", "")
        href = raw_href if isinstance(raw_href, str) else ""
        if "downloadfile.asp" in href:
            fname = a.get_text(strip=True)
            if fname and fname not in attachment_names_set:
                attachment_names_set.add(fname)
                attachments.append(fname)

    return ScrapeResult(title, date, content_html, images, attachments)


def scrape_business_detail(url):
    try:
        try:
            text = fetch_html_detail_cached(
                url,
                timeout=BUSINESS_SITE_FETCH.detail_timeout_seconds,
                encoding=BUSINESS_SITE_FETCH.detail_encoding,
                request_meta=BUSINESS_SITE_FETCH.detail_request_meta,
            )
        except HtmlTooLargeError as e:
            logger.warning("scrape_business_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_business_detail_from_html(text, url)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_business_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_business_notice_links_async(client: httpx.AsyncClient, list_url: str):
    try:
        text = await fetch_html_async(
            client,
            list_url,
            timeout=BUSINESS_SITE_FETCH.list_timeout_seconds,
            encoding=BUSINESS_SITE_FETCH.list_encoding,
        )
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        for td in soup.find_all("td", class_="Subject") or soup.find_all("td", class_="subject"):
            if not isinstance(td, Tag):
                continue
            a_tag = td.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = ensure_str_attr(a_tag.get("href", ""))
            title_text = a_tag.get_text(strip=True)
            if href:
                full_url = urljoin(list_url, href)
                prev_td = td.find_previous_sibling("td")
                no_text = prev_td.get_text(strip=True) if isinstance(prev_td, Tag) else ""
                if not no_text.isdigit():
                    no_text = ""
                links.append({"no": no_text, "url": full_url, "title_hint": title_text})
        return dedupe_link_dicts_by_url(links)
    except HtmlTooLargeError as e:
        logger.warning("get_business_notice_links_async body too large list_url=%s: %s", list_url, e)
        raise
    except Exception:
        logger.exception("get_business_notice_links_async parsing error list_url=%s", list_url)
        raise


async def scrape_business_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(
            client,
            url,
            timeout=BUSINESS_SITE_FETCH.detail_timeout_seconds,
            encoding=BUSINESS_SITE_FETCH.detail_encoding,
        )
        return parse_business_detail_from_html(text, url)
    except HtmlTooLargeError as e:
        logger.warning("scrape_business_detail_async body too large url=%s: %s", url, e)
        raise RequestException from e
    except Exception:
        logger.exception("scrape_business_detail_async error url=%s", url, exc_info=True)
        raise
