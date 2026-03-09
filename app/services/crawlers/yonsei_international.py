"""연세대 국제처 공지 크롤러. SeaLion-hub/crawler international.py 이식."""

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from requests.exceptions import RequestException

from app.core.crawl_http import (
    HtmlTooLargeError,
    fetch_html,
    fetch_html_detail_cached,
)
from app.core.crawler_config import CrawlerModuleSpec
from app.services.crawlers.base import ScrapeResult

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="international",
    display_name="국제처",
    list_url="https://oia.yonsei.ac.kr/news/newsIMain.asp",
    get_links="get_international_links",
    scrape_detail="scrape_international_detail",
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


def get_international_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_international_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []

        items = soup.find_all("li", class_=lambda c: c and ("img" in (c if isinstance(c, list) else [c]) or "no_img" in (c if isinstance(c, list) else [c])))
        for idx, item in enumerate(items):
            if not isinstance(item, Tag):
                continue
            a_tag = item.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = a_tag.get("href", "")
            if not href or href == "#" or "javascript:" in href:
                continue
            full_url = urljoin(list_url, href)
            title_elem = item.find(["strong", "h3", "h4"]) or item.find(class_=lambda c: c and "title" in (c or ""))
            if title_elem and isinstance(title_elem, Tag):
                title = title_elem.get_text(strip=True)
            else:
                title = a_tag.get_text(separator=" ", strip=True)
            if not title:
                continue
            num_elem = item.find(class_=lambda c: c and "num" in (c or ""))
            num_text = num_elem.get_text(strip=True) if num_elem and isinstance(num_elem, Tag) else str(idx + 1)
            if not any(d["url"] == full_url for d in links):
                links.append({"no": num_text, "title_hint": title, "url": full_url})

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_international_links parsing error list_url=%s", list_url)
        raise


def scrape_international_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_international_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = "제목 없음"
        title_li = soup.find("li", class_="title_view")
        if title_li and isinstance(title_li, Tag):
            h4_tag = title_li.find("h4")
            if h4_tag and isinstance(h4_tag, Tag):
                title = h4_tag.get_text(strip=True)
            else:
                temp_li = BeautifulSoup(str(title_li), "html.parser")
                info = temp_li.find("div", class_="info_txt")
                if info:
                    info.decompose()
                title = temp_li.get_text(strip=True)

        date = "날짜 없음"
        info_div = soup.find("div", class_="info_txt")
        if info_div and isinstance(info_div, Tag):
            date_span = info_div.find("span", class_="date_txt")
            if date_span and isinstance(date_span, Tag):
                date = normalize_date(date_span.get_text(strip=True))
            else:
                info_text = info_div.get_text(separator=" ", strip=True)
                date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", info_text)
                if date_match:
                    date = normalize_date(date_match.group())

        content_html = ""
        images: list[dict[str, Any]] = []
        content_div = soup.find("div", class_="view_contents")

        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = img.get("src", "")
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
                    safe_url = urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
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
        for file_div in soup.find_all("div", class_="file_txt"):
            for a_tag in file_div.find_all("a"):
                href = a_tag.get("href", "")
                if href and not href.startswith("#") and "javascript" not in href:
                    fname = a_tag.get_text(separator=" ", strip=True).strip()
                    fname = re.sub(r"\([\d.,]+\s*(KB|MB|GB|Bytes?)\)", "", fname, flags=re.IGNORECASE).strip()
                    if fname and fname not in attachments:
                        attachments.append(fname)

        return ScrapeResult(title=title, date_str=date, html_content=content_html, images=images, attachments=attachments)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_international_detail error url=%s: %s", url, e)
        raise
