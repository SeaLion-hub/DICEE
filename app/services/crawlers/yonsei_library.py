"""연세대 도서관 공지 크롤러. SeaLion-hub/crawler library.py 이식."""

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
    college_code="library",
    display_name="도서관",
    list_url="https://library.yonsei.ac.kr/bbs/list/1?pn=1",
    get_links="get_library_links",
    scrape_detail="scrape_library_detail",
)

MAX_LINKS = 10


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


def get_library_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_library_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        count = 0

        for row in soup.find_all("tr"):
            if count >= MAX_LINKS:
                break
            row_tag = as_tag(row)
            if row_tag is None:
                continue
            row_classes = class_list_from_tag(row_tag)
            if "always" in row_classes:
                continue
            a_tag = row_tag.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = ensure_str_attr(a_tag.get("href"))
            if not href or href == "#" or "javascript:" in href:
                continue
            full_url = urljoin(list_url, href)
            title = a_tag.get_text(separator=" ", strip=True)
            if not title:
                continue
            num_text = "일반"
            tds = row_tag.find_all("td")
            if tds and isinstance(tds[0], Tag):
                num_text = tds[0].get_text(strip=True)
            if not any(d["url"] == full_url for d in links):
                links.append({"no": num_text, "title_hint": title, "url": full_url})
                count += 1

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_library_links parsing error list_url=%s", list_url)
        raise


def scrape_library_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_library_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = "제목 없음"
        date = "날짜 없음"
        board_info = soup.find("div", class_="boardInfo")
        if board_info and isinstance(board_info, Tag):
            info_text = board_info.get_text(separator=" ", strip=True)
            date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", info_text)
            if date_match:
                date = normalize_date(date_match.group())
            title_tag = board_info.find(["h2", "h3", "h4", "strong"])
            if title_tag and isinstance(title_tag, Tag):
                title = title_tag.get_text(strip=True)
            else:
                if date_match:
                    title = info_text.split(date_match.group())[0].strip()
                else:
                    title = info_text

        content_html = ""
        images: list[dict[str, Any]] = []
        board_content = soup.find("div", class_="boardContent")

        if board_content and isinstance(board_content, Tag):
            for idx, img in enumerate(board_content.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = ensure_str_attr(img.get("src"))
                if not src or any(x in src for x in ["icon", "btn", "blank"]):
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
            for table in board_content.find_all("table"):
                if isinstance(table, Tag) and not table.get("border"):
                    table["border"] = "1"
            content_html = board_content.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        attachments: list[str] = []
        additional_items = soup.find("div", class_="additionalItems")
        if additional_items and isinstance(additional_items, Tag):
            for raw_a in additional_items.find_all("a"):
                a_tag = as_tag(raw_a)
                if a_tag is None:
                    continue
                href = ensure_str_attr(a_tag.get("href"))
                if href and not href.startswith("#") and "javascript" not in href:
                    fname = a_tag.get_text(separator=" ", strip=True).strip()
                    fname = re.sub(r"\([\d.,]+\s*(KB|MB|GB|Bytes?)\)", "", fname, flags=re.IGNORECASE).strip()
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
        logger.exception("scrape_library_detail error url=%s: %s", url, e)
        raise
