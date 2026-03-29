import logging
import os
import urllib.parse
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Comment, Tag
from requests.exceptions import RequestException

from app.core.bs4_utils import as_tag
from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_async,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult
from app.services.crawlers.notice_dates import normalize_notice_date
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="science",
    display_name="이과대학",
    list_url="http://science.yonsei.ac.kr/community/notice",
    get_links="get_science_links",
    scrape_detail="scrape_science_detail",
)


# ================================================================================
# [1] 기존 이과대학 상세 크롤링 로직 (절대 수정 안 함, 원본 그대로)
# ================================================================================
def get_body_soup(soup):
    start_node = soup.find(string=lambda text: isinstance(text, Comment) and "게시물 내용" in text and "//" not in text)
    if not start_node:
        return None

    end_comment = soup.find(string=lambda text: isinstance(text, Comment) and "// 게시물 내용" in text)

    temp_html = ""
    curr = start_node.next_sibling
    while curr and curr != end_comment:
        temp_html += str(curr)
        curr = curr.next_sibling

    temp_soup = BeautifulSoup(temp_html, "html.parser")

    files_div = temp_soup.find("div", class_="nxb-view__files")
    if files_div:
        for element in files_div.find_all_next():
            element.extract()
        files_div.extract()

    return temp_soup


def parse_science_links_from_html(html: str, list_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, Any]] = []
    rows = soup.select(".nxb-list-table tbody tr")
    for row in rows:
        if not isinstance(row, Tag):
            continue
        num_td = row.find("td", class_="nxb-list-table__num")
        if not num_td or not isinstance(num_td, Tag):
            continue
        if num_td.find("i", class_="nxb-list-table__notice-icon"):
            continue
        num = num_td.get_text(strip=True)
        if not num.isdigit():
            continue
        title_td = row.find("td", class_="nxb-list-table__title")
        if title_td and isinstance(title_td, Tag):
            a_tag = title_td.find("a")
            if a_tag and isinstance(a_tag, Tag):
                href = ensure_str_attr(a_tag.get("href"))
                if not href:
                    continue
                full_url = urljoin(list_url, href)
                links.append({"no": num, "title_hint": a_tag.get_text(strip=True), "url": full_url})
    return links


def parse_science_detail_from_html(html: str, detail_url: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    title = "제목 없음"
    t_tag = soup.find("h3", class_="nxb-view__header-title")
    if t_tag:
        title = t_tag.get_text(strip=True)
    date = "날짜 없음"
    for dt in soup.find_all("div", class_="nxb-view__info-dt"):
        if "작성일" in dt.get_text():
            dd = dt.find_next_sibling("div", class_="nxb-view__info-dd")
            if dd:
                date = normalize_notice_date(dd.get_text(strip=True))
                break
    content_html = ""
    images: list[dict[str, Any]] = []
    image_urls: set[str] = set()
    temp_soup = get_body_soup(soup)
    if temp_soup:
        for idx, img in enumerate(temp_soup.find_all("img")):
            img_tag = as_tag(img)
            if img_tag is None:
                continue
            src = ensure_str_attr(img_tag.get("src", ""))
            if src and not any(x in src for x in ["icon", "btn", "blank"]):
                if src.startswith("data:image"):
                    try:
                        header, encoded = src.split(",", 1)
                        ext = "png"
                        if "jpeg" in header or "jpg" in header:
                            ext = "jpg"
                        images.append({"type": "base64", "data": encoded, "name": f"image_{idx+1}.{ext}"})
                    except (ValueError, IndexError):
                        logger.warning(
                            "parse_science_detail_from_html inline image parse failed url=%s index=%s",
                            detail_url,
                            idx,
                            exc_info=True,
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
            img_tag.decompose()
        for table in temp_soup.find_all("table"):
            table_tag = as_tag(table)
            if table_tag is None:
                continue
            if not table_tag.get("border"):
                table_tag["border"] = "1"
        content_html = temp_soup.decode_contents().strip()
    else:
        content_html = "(본문 영역을 찾을 수 없습니다)"
    attachments: list[str] = []
    attachment_names: set[str] = set()
    for fdiv in soup.find_all("div", class_="file-name-area"):
        if not isinstance(fdiv, Tag):
            continue
        fname = "".join([node for node in fdiv.contents if isinstance(node, str)]).strip()
        if fname and fname not in attachment_names:
            attachment_names.add(fname)
            attachments.append(fname)
    return ScrapeResult(title, date, content_html, images, attachments)


def scrape_science_detail(url):
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_science_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_science_detail_from_html(text, url)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_science_detail parsing error url=%s, error=%s", url, e)
        raise


# ================================================================================
# [2] 이과대학 리스트 페이지 크롤러 (절대 수정 안 함, 원본 그대로)
# ================================================================================
def get_science_links(url):
    try:
        try:
            text = fetch_html(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_science_links body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_science_links_from_html(text, url)
    except RequestException:
        raise
    except Exception:
        logger.exception("get_science_links parsing error url=%s", url)
        raise


async def get_science_links_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        return parse_science_links_from_html(text, url)
    except Exception:
        logger.exception("get_science_links_async parsing error url=%s", url)
        raise


async def scrape_science_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        return parse_science_detail_from_html(text, url)
    except Exception:
        logger.exception("scrape_science_detail_async error url=%s", url)
        raise
