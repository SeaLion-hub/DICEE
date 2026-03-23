"""글로벌사회공헌원(IGEE) 공지 크롤러. SeaLion-hub/crawler igee.py 이식."""

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
from app.services.crawlers.typing_helpers import ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="igee",
    display_name="글로벌사회공헌원",
    list_url="https://igee.yonsei.ac.kr/board.php?mid=m04_01",
    get_links="get_igee_links",
    scrape_detail="scrape_igee_detail",
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


def get_igee_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_igee_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []

        for row in soup.find_all("tr"):
            row_tag = as_tag(row)
            if row_tag is None:
                continue
            a_tag = row_tag.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = ensure_str_attr(a_tag.get("href"))
            if not href or href == "#" or "javascript:" in href or "mailto:" in href:
                continue
            full_url = urljoin(list_url, href)
            title = a_tag.get_text(separator=" ", strip=True)
            if not title:
                continue
            num_text = "공지/일반"
            tds = row_tag.find_all("td")
            if tds and isinstance(tds[0], Tag):
                num_text = tds[0].get_text(strip=True)
            if not any(d["url"] == full_url for d in links):
                links.append({"no": num_text, "title_hint": title, "url": full_url})

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_igee_links parsing error list_url=%s", list_url)
        raise


def scrape_igee_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_igee_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = "제목 없음"
        title_div = soup.find("div", id="BoardViewTitle")
        if title_div and isinstance(title_div, Tag):
            title = title_div.get_text(strip=True)

        date = "날짜 없음"
        attachments: list[str] = []
        for b_add in soup.find_all("div", id="BoardViewAdd"):
            if not isinstance(b_add, Tag):
                continue
            text_content = b_add.get_text(separator=" ", strip=True)
            if "등록일" in text_content or re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", text_content):
                date = normalize_date(text_content)
            for raw_a in b_add.find_all("a"):
                a = as_tag(raw_a)
                if a is None:
                    continue
                href = ensure_str_attr(a.get("href"))
                if href and not href.startswith("#") and "javascript" not in href:
                    fname = a.get_text(separator=" ", strip=True).strip('"').strip()
                    fname = re.sub(r"\([\d.,]+\s*(KB|MB|GB|Bytes?)\)", "", fname, flags=re.IGNORECASE).strip()
                    if fname and fname not in attachments:
                        attachments.append(fname)

        content_html = ""
        images: list[dict[str, Any]] = []
        content_div = soup.find("div", id="BoardContent")

        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = ensure_str_attr(img.get("src"))
                if not src or any(x in src for x in ["icon", "btn", "blank", "ext_"]):
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
            for table in content_div.find_all("table"):
                if isinstance(table, Tag) and not table.get("border"):
                    table["border"] = "1"
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

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
        logger.exception("scrape_igee_detail error url=%s: %s", url, e)
        raise
