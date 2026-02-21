import logging
import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx
import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from requests.exceptions import RequestException

from app.core.crawler_config import CRAWLER_HEADERS
from app.core.crawl_http import fetch_html_async

logger = logging.getLogger(__name__)

# ==============================================================================
# [1] 상세 페이지 크롤링 엔진 (주석 타격 + 표 보존 + 날짜 통일)
# ==============================================================================

def normalize_date(date_str):
    """날짜를 YYYY.MM.DD 형식으로 통일"""
    try:
        clean_str = re.sub(r'[년월일/-]', '.', date_str)
        parts = [p.strip() for p in clean_str.split('.') if p.strip().isdigit()]
        if len(parts) >= 3:
            y, m, d = parts[:3]
            if len(y) == 2:
                y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning("normalize_date failed (format change?): date_str=%r", date_str[:100] if date_str else None)
        return date_str

def process_table_html(table_tag):
    for tag in table_tag(['script', 'style', 'noscript', 'iframe']):
        tag.decompose()
    if not table_tag.get('border'):
        table_tag['border'] = "1"
    return str(table_tag)

def get_text_structurally(element):
    if isinstance(element, NavigableString):
        return str(element)
    if element.name == 'table':
        return process_table_html(element)

    text = ""
    for child in element.children:
        if child.name in ['script', 'style', 'noscript']:
            continue
        if isinstance(child, Comment):
            continue
        if child.name == 'br':
            text += '\n'
            continue

        child_text = get_text_structurally(child)
        if child.name in ['div', 'p', 'li', 'dd', 'dt', 'tr', 'h1', 'h2', 'h3']:
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

def scrape_computing_detail(url):
    try:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. 제목
        title = "제목 없음"
        title_elem = soup.find(id="bo_v_title") or soup.find(class_="bo_v_title")
        if isinstance(title_elem, Tag):
            title = title_elem.get_text(strip=True)

        # 2. 날짜 (보통 bo_v_info 안에 있음)
        date = "날짜 없음"
        info_sec = soup.find(id="bo_v_info") or soup
        date_match = re.search(r'\d{2,4}\s*[.-]\s*\d{1,2}\s*[.-]\s*\d{1,2}', info_sec.get_text())
        if date_match:
            date = normalize_date(date_match.group())

        # 3. 본문 (주석 타격)
        content_text = ""
        images: list[dict[str, Any]] = []

        # '본문 내용 시작' ~ '본문 내용 끝' 주석 사이 추출
        body_tags = extract_between_comments(soup, "본문 내용 시작", "본문 내용 끝")

        if body_tags:
            temp_html = "".join(str(t) for t in body_tags)
            temp_soup = BeautifulSoup(temp_html, 'html.parser')

            content_text = get_text_structurally(temp_soup)
            content_text = re.sub(r'\n\s*\n+', '\n\n', content_text).strip()

            # 이미지
            for img in temp_soup.find_all('img'):
                if not isinstance(img, Tag):
                    continue
                raw_src = img.get('src', '')
                src = raw_src if isinstance(raw_src, str) else ""
                if not src:
                    continue
                if src.startswith('data:image'):
                    pass  # 생략
                else:
                    if any(x in src for x in ['icon', 'btn', 'blank']):
                        continue
                    # 그누보드는 보통 절대경로거나 /data/.. 형태
                    if src.startswith('/'):
                        full = "https://computing.yonsei.ac.kr" + src
                    else:
                        full = src

                    fname = os.path.basename(full.split('?')[0])
                    if not fname or '.' not in fname:
                        fname = "image.jpg"

                    if not any(d['data'] == full for d in images):
                        images.append({"type": "url", "data": full, "name": fname})
        else:
            content_text = "(본문을 찾을 수 없습니다)"

        # 4. 첨부파일 (주석 타격)
        attachments = []
        file_tags = extract_between_comments(soup, "첨부파일 시작", "첨부파일 끝")
        if file_tags:
            for t in file_tags:
                if isinstance(t, Tag):
                    for a in t.find_all('a'):
                        if not isinstance(a, Tag):
                            continue
                        # 그누보드 다운로드 링크 특징
                        href_val = a.get('href', '')
                        href_str = href_val if isinstance(href_val, str) else ''
                        if 'download.php' in href_str:
                            fname = a.get_text(strip=True)
                            if fname and fname not in attachments:
                                attachments.append(fname)

        return title, date, content_text, images, attachments

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
        response = requests.get(list_url, headers=CRAWLER_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        links = []

        # 그누보드 게시판은 보통 tbl_head01 클래스나 그냥 tbody 안의 tr을 씁니다.
        rows = soup.select('tbody tr')

        for row in rows:
            if not isinstance(row, Tag):
                continue
            cols = row.find_all('td')
            if not cols:
                continue

            # 첫 번째 컬럼: 번호 (td_num)
            # 공지사항은 여기에 '공지'라고 써있거나 strong 태그가 있음
            first_col = cols[0]
            num_text = first_col.get_text(strip=True) if isinstance(first_col, Tag) else ""

            # ★ 핵심 필터: 숫자인지 확인 (공지, Notice 등은 걸러짐)
            if num_text.isdigit():
                # 제목 컬럼 찾기 (보통 'td_subject' 클래스를 가짐)
                subject_td = row.find('td', class_='td_subject')
                if not subject_td or not isinstance(subject_td, Tag):
                    # 클래스가 없으면 두 번째(1번 인덱스) 컬럼을 제목으로 가정
                    if len(cols) > 1:
                        subject_td = cols[1]

                if isinstance(subject_td, Tag):
                    link_tag = subject_td.find('a')
                    if isinstance(link_tag, Tag):
                        href_val = link_tag.get('href')
                        if isinstance(href_val, str):
                            href_str = href_val
                        elif isinstance(href_val, list) and href_val:
                            href_str = href_val[0]
                        else:
                            href_str = ''
                        if href_str:
                            # 링크 추출
                            full_url = href_str
                            # 만약 상대경로라면 변환 (그누보드는 보통 절대경로를 줌)
                            if not full_url.startswith('http'):
                                full_url = urljoin(list_url, full_url)

                            links.append({
                                "no": num_text,
                                "url": full_url
                            })

        return links

    except RequestException:
        raise
    except Exception:
        logger.exception("get_computing_notice_links parsing error list_url=%s", list_url)
        return []


async def get_computing_notice_links_async(client: httpx.AsyncClient, list_url: str):
    try:
        text = await fetch_html_async(client, list_url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        links = []
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
            subject_td = row.find("td", class_="td_subject") or (cols[1] if len(cols) > 1 else None)
            if isinstance(subject_td, Tag):
                link_tag = subject_td.find("a")
                if isinstance(link_tag, Tag):
                    href_val = link_tag.get("href")
                    href_str = href_val if isinstance(href_val, str) else (href_val[0] if isinstance(href_val, list) and href_val else "")
                    if href_str:
                        full_url = urljoin(list_url, href_str) if not href_str.startswith("http") else href_str
                        links.append({"no": num_text, "url": full_url})
        return links
    except Exception:
        logger.exception("get_computing_notice_links_async parsing error list_url=%s", list_url)
        return []


async def scrape_computing_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        title = "제목 없음"
        title_elem = soup.find(id="bo_v_title") or soup.find(class_="bo_v_title")
        if isinstance(title_elem, Tag):
            title = title_elem.get_text(strip=True)
        date = "날짜 없음"
        info_sec = soup.find(id="bo_v_info") or soup
        date_match = re.search(r"\d{2,4}\s*[.-]\s*\d{1,2}\s*[.-]\s*\d{1,2}", info_sec.get_text())
        if date_match:
            date = normalize_date(date_match.group())
        content_text = ""
        images: list[dict[str, Any]] = []
        body_tags = extract_between_comments(soup, "본문 내용 시작", "본문 내용 끝")
        if body_tags:
            temp_html = "".join(str(t) for t in body_tags)
            temp_soup = BeautifulSoup(temp_html, "html.parser")
            content_text = get_text_structurally(temp_soup)
            content_text = re.sub(r"\n\s*\n+", "\n\n", content_text).strip()
            for img in temp_soup.find_all("img"):
                if not isinstance(img, Tag):
                    continue
                src = img.get("src", "") or ""
                if not src or src.startswith("data:image"):
                    continue
                if any(x in src for x in ["icon", "btn", "blank"]):
                    continue
                full = "https://computing.yonsei.ac.kr" + src if src.startswith("/") else src
                fname = os.path.basename(full.split("?")[0]) or "image.jpg"
                if not any(d["data"] == full for d in images):
                    images.append({"type": "url", "data": full, "name": fname})
        else:
            content_text = "(본문을 찾을 수 없습니다)"
        attachments = []
        file_tags = extract_between_comments(soup, "첨부파일 시작", "첨부파일 끝")
        if file_tags:
            for t in file_tags:
                if isinstance(t, Tag):
                    for a in t.find_all("a"):
                        if isinstance(a, Tag):
                            href_str = a.get("href") or ""
                            if "download.php" in href_str:
                                fname = a.get_text(strip=True)
                                if fname and fname not in attachments:
                                    attachments.append(fname)
        return title, date, content_text, images, attachments
    except Exception as e:
        logger.exception("scrape_computing_detail_async error url=%s", url)
        raise
