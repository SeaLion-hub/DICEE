"""연세대 메인 공지 크롤러. SeaLion-hub/crawler main.py 이식."""

import base64
import logging
import os
import re
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Comment, Tag
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
    college_code="main",
    display_name="연세대 메인 공지",
    list_url="https://www.yonsei.ac.kr/sc/254/subview.do",
    get_links="get_yonsei_main_links",
    scrape_detail="scrape_yonsei_main_detail",
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


def get_yonsei_main_links(list_url: str) -> list[dict[str, Any]]:
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_yonsei_main_links body too large list_url=%s: %s", list_url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []

        notice_end_comment = soup.find(string=lambda t: isinstance(t, Comment) and "Notice" in t and "//" in t)
        items_to_parse: list[Tag] = []

        if notice_end_comment:
            curr = notice_end_comment.next_sibling
            while curr:
                if isinstance(curr, Tag) and curr.name == "li":
                    if "board-noti" not in (curr.get("class") or []):
                        items_to_parse.append(curr)
                curr = getattr(curr, "next_sibling", None)
        else:
            for li in soup.find_all("li"):
                if isinstance(li, Tag) and "board-noti" not in (li.get("class") or []):
                    items_to_parse.append(li)

        for li in items_to_parse:
            if not isinstance(li, Tag):
                continue
            a_tag = li.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = a_tag.get("href")
            if not href or href == "#" or "javascript:void" in str(href):
                continue
            full_url = urljoin(list_url, href)
            num_div = a_tag.find("div", class_="num")
            if not num_div or not isinstance(num_div, Tag):
                continue
            num_text = num_div.get_text(strip=True)
            if not num_text.isdigit():
                continue
            title_div = a_tag.find("div", class_=lambda c: c and "title" in (c or ""))
            if title_div and isinstance(title_div, Tag):
                strong = title_div.find("strong")
                title = strong.get_text(strip=True) if strong and isinstance(strong, Tag) else title_div.get_text(strip=True)
            else:
                title = a_tag.get_text(separator=" ", strip=True)
            title = title.replace("새글", "").strip()
            if not any(d["url"] == full_url for d in links):
                links.append({"no": num_text, "title_hint": title, "url": full_url})

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_yonsei_main_links parsing error list_url=%s", list_url)
        raise


def scrape_yonsei_main_detail(url: str) -> ScrapeResult:
    try:
        try:
            text = fetch_html_detail_cached(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_yonsei_main_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        title = "제목 없음"
        title_div = soup.find("div", class_="title")
        if title_div and isinstance(title_div, Tag):
            temp_soup = BeautifulSoup(str(title_div), "html.parser")
            detail_ul = temp_soup.find("ul", class_="detail")
            if detail_ul:
                detail_ul.decompose()
            strong_tag = temp_soup.find("strong")
            title = strong_tag.get_text(strip=True) if strong_tag and isinstance(strong_tag, Tag) else temp_soup.get_text(strip=True)

        date = "날짜 없음"
        date_span = soup.find(lambda tag: tag.name == "span" and "작성일" in (tag.get_text() or ""))
        if date_span and date_span.parent and isinstance(date_span.parent, Tag):
            raw_date_text = date_span.parent.get_text(separator=" ", strip=True).replace("작성일", "").strip()
            date = normalize_date(raw_date_text)

        content_html = ""
        images: list[dict[str, Any]] = []
        content_div = soup.find("div", class_="txt")

        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = img.get("src", "")
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
        attach_div = soup.find("div", class_="attachment")
        if attach_div and isinstance(attach_div, Tag):
            for a_tag in attach_div.find_all("a"):
                fname = a_tag.get_text(strip=True) if isinstance(a_tag, Tag) else ""
                if fname and fname not in attachments:
                    attachments.append(fname)

        return ScrapeResult(title=title, date_str=date, html_content=content_html, images=images, attachments=attachments)
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_yonsei_main_detail error url=%s: %s", url, e)
        raise
