import logging
import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Comment, Tag
from bs4.element import NavigableString
from requests.exceptions import RequestException

from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_async,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult
from app.services.crawlers.notice_dates import normalize_notice_date_split_tokens
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="ai",
    display_name="인공지능융합대학",
    list_url="https://computing.yonsei.ac.kr/bbs/board.php?bo_table=sub4_4",
    get_links="get_computing_notice_links",
    scrape_detail="scrape_computing_detail",
)

# ==============================================================================
# [1] 상세 페이지 크롤링 엔진 (주석 타격 + 표 보존 + 날짜 통일)
# ==============================================================================


def process_table_html(table_tag):
    for tag in table_tag(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    if not table_tag.get("border"):
        table_tag["border"] = "1"
    return str(table_tag)


def get_text_structurally(element):
    if isinstance(element, NavigableString):
        return str(element)
    if element.name == "table":
        return process_table_html(element)

    text = ""
    for child in element.children:
        if child.name in ["script", "style", "noscript"]:
            continue
        if isinstance(child, Comment):
            continue
        if child.name == "br":
            text += "\n"
            continue

        child_text = get_text_structurally(child)
        if child.name in ["div", "p", "li", "dd", "dt", "tr", "h1", "h2", "h3"]:
            if child_text.strip() or "<table" in child_text:
                text += "\n" + child_text.strip() + "\n"
        else:
            text += child_text
    return text


def extract_between_comments(soup, start_keyword, end_keyword):
    start_comment = soup.find(string=lambda t: isinstance(t, Comment) and start_keyword in t)
    if not start_comment:
        return None

    tags = []
    curr = start_comment.next_sibling
    while curr:
        if isinstance(curr, Comment) and end_keyword in curr:
            break
        if isinstance(curr, Tag) or (isinstance(curr, NavigableString) and curr.strip()):
            tags.append(curr)
        curr = curr.next_sibling
    return tags


def parse_computing_detail_from_html(html: str, detail_url: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    title = "제목 없음"
    title_elem = soup.find(id="bo_v_title") or soup.find(class_="bo_v_title")
    if isinstance(title_elem, Tag):
        title = title_elem.get_text(strip=True)
    date = "날짜 없음"
    info_sec = soup.find(id="bo_v_info") or soup
    date_match = re.search(r"\d{2,4}\s*[.-]\s*\d{1,2}\s*[.-]\s*\d{1,2}", info_sec.get_text())
    if date_match:
        date = normalize_notice_date_split_tokens(date_match.group())
    content_text = ""
    images: list[dict[str, Any]] = []
    image_urls: set[str] = set()
    body_tags = extract_between_comments(soup, "본문 내용 시작", "본문 내용 끝")
    if body_tags:
        temp_html = "".join(str(t) for t in body_tags)
        temp_soup = BeautifulSoup(temp_html, "html.parser")
        content_text = get_text_structurally(temp_soup)
        content_text = re.sub(r"\n\s*\n+", "\n\n", content_text).strip()
        for img in temp_soup.find_all("img"):
            if not isinstance(img, Tag):
                continue
            src = ensure_str_attr(img.get("src", ""))
            if not src or src.startswith("data:image"):
                continue
            if any(x in src for x in ["icon", "btn", "blank"]):
                continue
            full = "https://computing.yonsei.ac.kr" + src if src.startswith("/") else src
            fname = os.path.basename(full.split("?")[0])
            if not fname or "." not in fname:
                fname = "image.jpg"
            if full not in image_urls:
                image_urls.add(full)
                images.append({"type": "url", "data": full, "name": fname})
    else:
        content_text = "(본문을 찾을 수 없습니다)"
    attachments: list[str] = []
    attachment_names: set[str] = set()
    file_tags = extract_between_comments(soup, "첨부파일 시작", "첨부파일 끝")
    if file_tags:
        for t in file_tags:
            if isinstance(t, Tag):
                for a in t.find_all("a"):
                    if not isinstance(a, Tag):
                        continue
                    href_str = ensure_str_attr(a.get("href"))
                    if "download.php" in href_str:
                        fname = a.get_text(strip=True)
                        if fname and fname not in attachment_names:
                            attachment_names.add(fname)
                            attachments.append(fname)
    return ScrapeResult(title, date, content_text, images, attachments)


def parse_computing_notice_links_from_html(html: str, list_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[dict[str, Any]] = []
    for row in soup.select("tbody tr"):
        if not isinstance(row, Tag):
            continue
        cols = row.find_all("td")
        if not cols:
            continue
        first_col = cols[0]
        num_text = first_col.get_text(strip=True) if isinstance(first_col, Tag) else ""
        if not num_text.isdigit():
            continue
        subject_td = row.find("td", class_="td_subject")
        if not subject_td or not isinstance(subject_td, Tag):
            if len(cols) > 1:
                subject_td = cols[1]
        if isinstance(subject_td, Tag):
            link_tag = subject_td.find("a")
            if isinstance(link_tag, Tag):
                href_val = link_tag.get("href")
                if isinstance(href_val, str):
                    href_str = href_val
                elif isinstance(href_val, list) and href_val:
                    href_str = href_val[0]
                else:
                    href_str = ""
                if href_str:
                    full_url = href_str if href_str.startswith("http") else urljoin(list_url, href_str)
                    links.append({"no": num_text, "url": full_url})
    return links


def scrape_computing_detail(url):
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_computing_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_computing_detail_from_html(text, url)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_computing_detail parsing error url=%s, error=%s", url, e)
        raise


# ==============================================================================
# [2] 목록(List) 크롤링 엔진 (NEW)
# ==============================================================================


def get_computing_notice_links(list_url):
    """
    그누보드 게시판 목록에서 '공지'를 제외하고 '번호'가 있는 게시물의 링크를 추출합니다.
    """
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_computing_notice_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        return parse_computing_notice_links_from_html(text, list_url)
    except RequestException:
        raise
    except Exception:
        logger.exception("get_computing_notice_links parsing error list_url=%s", list_url)
        raise


async def get_computing_notice_links_async(client: httpx.AsyncClient, list_url: str):
    try:
        text = await fetch_html_async(client, list_url, timeout=10.0)
        return parse_computing_notice_links_from_html(text, list_url)
    except Exception:
        logger.exception("get_computing_notice_links_async parsing error list_url=%s", list_url)
        raise


async def scrape_computing_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        return parse_computing_detail_from_html(text, url)
    except Exception:
        logger.exception("scrape_computing_detail_async error url=%s", url)
        raise
