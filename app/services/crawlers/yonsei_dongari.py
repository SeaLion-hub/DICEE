"""연세대 총동아리연합회 공지 크롤러. SeaLion-hub/crawler dongari.py 이식."""

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
from app.services.crawlers.base import ScrapeResult, require_non_empty_text, require_present
from app.services.crawlers.notice_dates import normalize_notice_date
from app.services.crawlers.typing_helpers import class_list_from_tag, ensure_str_attr

logger = logging.getLogger(__name__)

CRAWLER_SPEC = CrawlerModuleSpec(
    college_code="dongari",
    display_name="총동아리연합회",
    list_url="https://dongari.yonsei.ac.kr/kr/notice/notice.php",
    get_links="get_dongari_links",
    scrape_detail="scrape_dongari_detail",
)


def get_dongari_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_dongari_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []

        for row in soup.find_all("div", class_="bbs-list-row"):
            row_tag = as_tag(row)
            if row_tag is None:
                continue
            row_classes = class_list_from_tag(row_tag)
            if "notice-row" in row_classes:
                continue
            a_tag = row_tag.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = ensure_str_attr(a_tag.get("href"))
            if not href or href == "#" or "javascript:" in href:
                continue
            full_url = urljoin(list_url, href)
            title_elem = row_tag.find(class_=lambda c: c and "tit" in (c or ""))
            title_el = as_tag(title_elem)
            if title_el is not None and title_el.name != "a":
                title = title_el.get_text(strip=True)
            else:
                title = a_tag.get_text(strip=True)
            if not title:
                continue
            num_elem = row_tag.find(class_=lambda c: c and "num" in (c or ""))
            num_el = as_tag(num_elem)
            num_text = num_el.get_text(strip=True) if num_el is not None else "일반"
            if not any(d["url"] == full_url for d in links):
                links.append({"no": num_text, "title_hint": title, "url": full_url})

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_dongari_links parsing error list_url=%s", list_url)
        raise


def scrape_dongari_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_dongari_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = ""
        title_tag = soup.find("h1", class_="bbs-tit")
        if title_tag and isinstance(title_tag, Tag):
            title = title_tag.get_text(strip=True)
        title = require_non_empty_text(title, field="title", url=url)

        date = "날짜 없음"
        info_dl = soup.find("dl", class_="bbs-write-info")
        if info_dl:
            info_text = info_dl.get_text(separator=" ", strip=True)
            if "등록일" in info_text:
                date_part = info_text.split("등록일")[1]
                date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", date_part)
                if date_match:
                    date = normalize_notice_date(date_match.group())
            if date == "날짜 없음":
                date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", info_text)
                if date_match:
                    date = normalize_notice_date(date_match.group())

        content_html = ""
        images: list[dict[str, Any]] = []
        content_div = soup.find("div", class_="bbs-view-content")
        content_div = require_present(
            content_div if isinstance(content_div, Tag) else None,
            selector="div.bbs-view-content",
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
                fname = os.path.basename(unquoted_path)
                if not any(d.get("data") == safe_url for d in images):
                    images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx + 1}.jpg"})
            img.decompose()
        for table in content_div.find_all("table"):
            if isinstance(table, Tag) and not table.get("border"):
                table["border"] = "1"
        content_html = require_non_empty_text(content_div.decode_contents().strip(), field="content_html", url=url)

        attachments: list[str] = []
        for fl in soup.find_all("dl", class_="bbs-file-list"):
            fl_tag = as_tag(fl)
            if fl_tag is None:
                continue
            for raw_a in fl_tag.find_all("a"):
                a_tag = as_tag(raw_a)
                if a_tag is None:
                    continue
                href = ensure_str_attr(a_tag.get("href"))
                if href and not href.startswith("#") and "javascript" not in href:
                    fname = ensure_str_attr(a_tag.get("download")) or a_tag.get_text(strip=True)
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
        logger.exception("scrape_dongari_detail error url=%s: %s", url, e)
        raise
