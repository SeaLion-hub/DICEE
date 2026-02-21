import logging
import os
import re
from urllib.parse import urljoin
import httpx
import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from bs4.element import PageElement
from requests.exceptions import RequestException

from app.core.crawler_config import CRAWLER_HEADERS
from app.core.crawl_http import HtmlTooLargeError, fetch_html, fetch_html_async

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------
# [1] 기존 상세 페이지 크롤링 로직 (주석 무시 로직 추가)
# --------------------------------------------------------------------------------
def process_table_html(table_tag: Tag) -> str:
    for tag in table_tag(['script', 'style', 'noscript', 'iframe']):
        if isinstance(tag, Tag):
            tag.decompose()
    if not table_tag.get('border'):
        table_tag['border'] = "1"
    return str(table_tag)

def get_text_structurally(element: PageElement) -> str:
    # ★ 버그 수정: HTML 주석(Comment)인 경우 텍스트로 취급하지 않고 빈 문자열 반환
    if isinstance(element, Comment):
        return ""
    if not isinstance(element, Tag | NavigableString):
        return ""

    text_content = ""
    if isinstance(element, NavigableString):
        return str(element)
    if isinstance(element, Tag) and element.name == 'table':
        return process_table_html(element)

    for child in element.children:
        # ★ 버그 수정: 자식 노드 탐색 시에도 주석이면 건너뜀
        if isinstance(child, Comment):
            continue
        if isinstance(child, Tag) and child.name in ['script', 'style', 'noscript']:
            continue
        if isinstance(child, Tag) and child.name == 'br':
            text_content += '\n'
            continue

        child_text = get_text_structurally(child)
        block_tags = ['div', 'p', 'li', 'tr', 'h1', 'h2', 'h3', 'option', 'dd', 'dt']
        if isinstance(child, Tag) and child.name in block_tags:
            if child_text.strip() or "<table" in child_text:
                text_content += "\n" + child_text.strip() + "\n"
        else:
            text_content += child_text
    return text_content

def finalize_text(text):
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()

def scrape_yonsei_engineering_precise(url):
    try:
        try:
            text = fetch_html(url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("scrape_yonsei_engineering_precise body too large url=%s: %s", url, e)
            return None, "접속 실패", None, [], []
        except RequestException:
            return None, "접속 실패", None, [], []
        soup = BeautifulSoup(text, "html.parser")

        # 제목
        title = "제목 없음"
        title_label = soup.find(string=lambda t: t and "제목" in t)
        if title_label:
            title_container = title_label.find_parent(['dt', 'th', 'td'])
            if title_container:
                title_elem = title_container.find_next_sibling(['dd', 'td'])
                if title_elem:
                    title = get_text_structurally(title_elem).strip()
        if title == "제목 없음":
            h3 = soup.find('h3')
            if h3:
                title = get_text_structurally(h3).strip()

        # 게시일
        date = "날짜 없음"
        date_match = re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', soup.get_text())
        if date_match:
            date = date_match.group()

        # 본문 (정밀 타격)
        content_text = ""
        main_container = None
        anchor_text = soup.find(string=lambda t: t and "게시글 내용" in t)
        if anchor_text:
            start_tag = anchor_text.find_parent(['dt', 'th', 'td'])
            if start_tag and isinstance(start_tag, Tag):
                target_body = start_tag.find_next_sibling(['dd', 'td'])
                if target_body and isinstance(target_body, Tag):
                    main_container = target_body
                    garbage_selectors = ['.btn_area', '.btn-wrap', '#bo_v_share', 'ul.btn_bo_user', 'div.btn_confirm']
                    for selector in garbage_selectors:
                        for tag in main_container.select(selector):
                            tag.decompose()
                    raw_text = get_text_structurally(main_container)
                    stop_keywords = ["관리자 if문", "답변글 버튼", "목록 List 버튼", "등록 버튼"]
                    for keyword in stop_keywords:
                        if keyword in raw_text:
                            raw_text = raw_text.split(keyword)[0]
                    content_text = finalize_text(raw_text)

        if not content_text:
            content_text = "(본문 영역인 <dd> 태그를 찾지 못했습니다.)"

        # 이미지
        images_data = []
        seen_image_urls: set[str] = set()
        if main_container and isinstance(main_container, Tag):
            img_tags = main_container.find_all('img')
            for idx, img in enumerate(img_tags):
                if not isinstance(img, Tag):
                    continue
                raw_src = img.get('src', '')
                src = raw_src if isinstance(raw_src, str) else ''
                if not src:
                    continue
                if src.startswith('data:image'):
                    try:
                        header, encoded = src.split(',', 1)
                        ext = "png"
                        if "jpeg" in header or "jpg" in header:
                            ext = "jpg"
                        images_data.append({
                            "type": "base64",
                            "data": encoded,
                            "ext": ext,
                            "name": f"image_{idx+1}.{ext}",
                        })
                    except Exception:
                        continue
                else:
                    if any(x in src for x in ['icon', 'btn', 'button', 'search', 'blank']):
                        continue
                    if src.startswith('/'):
                        full_url = 'https://engineering.yonsei.ac.kr' + src
                    elif src.startswith('http'):
                        full_url = src
                    else:
                        continue
                    if full_url in seen_image_urls:
                        continue
                    seen_image_urls.add(full_url)
                    fn_raw = img.get('data-file_name')
                    file_name = fn_raw if isinstance(fn_raw, str) and fn_raw else os.path.basename(src.split('?')[0])
                    if not file_name or '.' not in file_name:
                        file_name = f"image_{idx+1}.jpg"
                    images_data.append({
                        "type": "url",
                        "data": full_url,
                        "ext": file_name.split('.')[-1],
                        "name": file_name,
                    })

        # 첨부파일
        attachment_names = []
        attach_labels = soup.find_all(string=re.compile("첨부"))
        for label in attach_labels:
            parent_row = label.find_parent(['tr', 'li', 'div', 'dl', 'dt', 'dd'])
            if isinstance(parent_row, Tag) and parent_row.name == 'dt':
                next_dd = parent_row.find_next_sibling('dd')
                parent_row = next_dd if isinstance(next_dd, Tag) else parent_row
            if isinstance(parent_row, Tag):
                links = parent_row.find_all('a')
                for link in links:
                    if not isinstance(link, Tag):
                        continue
                    file_name = link.get_text(strip=True)
                    raw_href = link.get('href', '')
                    href = raw_href if isinstance(raw_href, str) else ''
                    if href and not href.startswith('#') and 'javascript' not in href:
                         if file_name and file_name not in attachment_names:
                             attachment_names.append(file_name)

        return title, date, content_text, images_data, attachment_names

    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_yonsei_engineering_precise parsing error url=%s, error=%s", url, e)
        raise

# --------------------------------------------------------------------------------
# [2] 리스트 페이지 크롤러
# --------------------------------------------------------------------------------
def get_notice_links(list_url):
    try:
        try:
            text = fetch_html(list_url, timeout=10)
        except HtmlTooLargeError as e:
            logger.warning("get_notice_links body too large list_url=%s: %s", list_url, e)
            return []
        except RequestException:
            return []
        soup = BeautifulSoup(text, "html.parser")
        links = []
        rows = soup.select('tbody tr')

        for row in rows:
            if not isinstance(row, Tag):
                continue
            cols = row.find_all('td')
            if not cols:
                continue

            first_col = cols[0]
            num_text = first_col.get_text(strip=True) if isinstance(first_col, Tag) else ""
            if num_text.isdigit():
                link_tag = row.find('a')
                if isinstance(link_tag, Tag):
                    href_val = link_tag.get('href')
                    if isinstance(href_val, str):
                        href_str = href_val
                    elif isinstance(href_val, list) and href_val:
                        href_str = href_val[0]
                    else:
                        href_str = ''
                    if href_str:
                        full_url = urljoin(list_url, href_str)
                        links.append({
                            "no": num_text,
                            "url": full_url
                        })

        return links

    except RequestException:
        raise
    except Exception:
        logger.exception("get_notice_links parsing error list_url=%s", list_url)
        return []


async def get_notice_links_async(client: httpx.AsyncClient, list_url: str):
    """비동기: 목록 URL에서 공지 링크 수집."""
    try:
        text = await fetch_html_async(client, list_url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        links = []
        seen_urls: set[str] = set()
        rows = soup.select("tbody tr")
        for row in rows:
            if not isinstance(row, Tag):
                continue
            cols = row.find_all("td")
            if not cols:
                continue
            first_col = cols[0]
            num_text = first_col.get_text(strip=True) if isinstance(first_col, Tag) else ""
            if num_text.isdigit():
                link_tag = row.find("a")
                if isinstance(link_tag, Tag):
                    href_val = link_tag.get("href")
                    href_str = href_val if isinstance(href_val, str) else (href_val[0] if isinstance(href_val, list) and href_val else "")
                    if href_str:
                        full_url = urljoin(list_url, href_str)
                        if full_url not in seen_urls:
                            seen_urls.add(full_url)
                            links.append({"no": num_text, "url": full_url})
        return links
    except HtmlTooLargeError as e:
        logger.warning("get_notice_links_async body too large list_url=%s: %s", list_url, e)
        return []
    except Exception:
        logger.exception("get_notice_links_async parsing error list_url=%s", list_url)
        return []


async def scrape_yonsei_engineering_precise_async(client: httpx.AsyncClient, url: str):
    """비동기: 상세 페이지 스크래핑. 반환 (title, date, content_text, images_data, attachment_names)."""
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        title = "제목 없음"
        title_label = soup.find(string=lambda t: t and "제목" in t)
        if title_label:
            title_container = title_label.find_parent(["dt", "th", "td"])
            if title_container:
                title_elem = title_container.find_next_sibling(["dd", "td"])
                if title_elem:
                    title = get_text_structurally(title_elem).strip()
        if title == "제목 없음":
            h3 = soup.find("h3")
            if h3:
                title = get_text_structurally(h3).strip()
        date = "날짜 없음"
        date_match = re.search(r"\d{4}[.-]\d{2}[.-]\d{2}", soup.get_text())
        if date_match:
            date = date_match.group()
        content_text = ""
        main_container = None
        anchor_text = soup.find(string=lambda t: t and "게시글 내용" in t)
        if anchor_text:
            start_tag = anchor_text.find_parent(["dt", "th", "td"])
            if start_tag and isinstance(start_tag, Tag):
                target_body = start_tag.find_next_sibling(["dd", "td"])
                if target_body and isinstance(target_body, Tag):
                    main_container = target_body
                    for selector in [".btn_area", ".btn-wrap", "#bo_v_share", "ul.btn_bo_user", "div.btn_confirm"]:
                        for tag in main_container.select(selector):
                            tag.decompose()
                    raw_text = get_text_structurally(main_container)
                    for keyword in ["관리자 if문", "답변글 버튼", "목록 List 버튼", "등록 버튼"]:
                        if keyword in raw_text:
                            raw_text = raw_text.split(keyword)[0]
                    content_text = finalize_text(raw_text)
        if not content_text:
            content_text = "(본문 영역인 <dd> 태그를 찾지 못했습니다.)"
        images_data = []
        image_urls_async: set[str] = set()
        if main_container and isinstance(main_container, Tag):
            for idx, img in enumerate(main_container.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = img.get("src", "") or ""
                if not src:
                    continue
                if src.startswith("data:image"):
                    try:
                        header, encoded = src.split(",", 1)
                        ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
                        images_data.append({"type": "base64", "data": encoded, "ext": ext, "name": f"image_{idx+1}.{ext}"})
                    except Exception:
                        continue
                else:
                    if any(x in src for x in ["icon", "btn", "button", "search", "blank"]):
                        continue
                    full_url = "https://engineering.yonsei.ac.kr" + src if src.startswith("/") else (src if src.startswith("http") else None)
                    if full_url and full_url not in image_urls_async:
                        image_urls_async.add(full_url)
                        fn_raw = img.get("data-file_name")
                        file_name = fn_raw if isinstance(fn_raw, str) and fn_raw else os.path.basename(src.split("?")[0])
                        if not file_name or "." not in file_name:
                            file_name = f"image_{idx+1}.jpg"
                        images_data.append({"type": "url", "data": full_url, "ext": file_name.split(".")[-1], "name": file_name})
        attachment_names = []
        attachment_names_set: set[str] = set()
        for label in soup.find_all(string=re.compile("첨부")):
            parent_row = label.find_parent(["tr", "li", "div", "dl", "dt", "dd"])
            if isinstance(parent_row, Tag) and parent_row.name == "dt":
                next_dd = parent_row.find_next_sibling("dd")
                parent_row = next_dd if isinstance(next_dd, Tag) else parent_row
            if isinstance(parent_row, Tag):
                for link in parent_row.find_all("a"):
                    if not isinstance(link, Tag):
                        continue
                    file_name = link.get_text(strip=True)
                    href = link.get("href", "") or ""
                    if href and not href.startswith("#") and "javascript" not in href and file_name and file_name not in attachment_names_set:
                        attachment_names_set.add(file_name)
                        attachment_names.append(file_name)
        return title, date, content_text, images_data, attachment_names
    except HtmlTooLargeError as e:
        logger.warning("scrape_yonsei_engineering_precise_async body too large url=%s: %s", url, e)
        return None, "본문 초과", None, [], []
    except Exception as e:
        logger.exception("scrape_yonsei_engineering_precise_async error url=%s", url)
        raise
