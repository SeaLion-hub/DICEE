import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
import requests
from bs4 import BeautifulSoup, Comment, Tag
from bs4.element import PageElement
from requests.exceptions import RequestException

from app.core.crawler_config import CRAWLER_HEADERS
from app.core.crawl_http import fetch_html_async

logger = logging.getLogger(__name__)

# ==============================================================================
# [1] 유틸리티 함수
# ==============================================================================

def normalize_date(date_str):
    """날짜 문자열을 YYYY.MM.DD로 표준화"""
    try:
        clean = re.sub(r'[년월일/-]', '.', date_str)
        parts = [p.strip() for p in clean.split('.') if p.strip().isdigit()]
        if len(parts) >= 3:
            y, m, d = parts[:3]
            if len(y) == 2:
                y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning("normalize_date failed (format change?): date_str=%r", date_str[:100] if date_str else None)
        return date_str

def clean_html_content(element: Tag) -> str:
    """HTML 본문 정제 (스크립트 제거, 표 보존). 원본 보호를 위해 문자열로 깊은 복사."""
    element_copy = BeautifulSoup(str(element), 'html.parser')

    # 보안상 제거
    for tag in element_copy.find_all(['script', 'style', 'noscript', 'iframe', 'img']):
        tag.decompose()

    # 표 테두리 강제 적용
    for table in element_copy.find_all('table'):
        if not isinstance(table, Tag):
            continue
        if not table.get('border'):
            table['border'] = "1"

    return element_copy.decode_contents().strip()

# ==============================================================================
# [2] 목록 수집 엔진 (List Crawler) - 수정됨
# ==============================================================================

def get_medicine_notice_links(list_url):
    """
    게시판 목록에서 'bbs-item' 클래스를 가진 요소들의 링크를 수집합니다.
    (페이지네이션 버튼 전까지만 수집하는 효과)
    """
    try:
        response = requests.get(list_url, headers=CRAWLER_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        links: list[dict[str, Any]] = []

        # ★ 핵심 수정: 주석 대신 'bbs-item' 클래스를 직접 타격
        # 스크린샷 분석 결과, 각 게시물은 <div class="bbs-item ..."> 안에 있음
        items = [t for t in soup.find_all('div', class_='bbs-item') if isinstance(t, Tag)]

        if not items:
            # 혹시 모를 예비책: bbs-list 클래스나 일반적인 리스트 구조 확인
            fallback = soup.select('.bbs-list li') or soup.select('tbody tr')
            items = [t for t in fallback if isinstance(t, Tag)]

        for item in items:
            if not isinstance(item, Tag):
                continue
            # 링크(a 태그) 찾기
            a_tag = item.find('a')
            if not a_tag or not isinstance(a_tag, Tag):
                continue

            raw_href = a_tag.get('href', '')
            href = raw_href if isinstance(raw_href, str) else ''

            # 유효한 게시물 링크인지 검증 (articleNo 또는 mode=view 포함 여부)
            if 'articleNo' in href or 'mode=view' in href:
                full_url = urljoin(list_url, href)
                # URL 쿼리에서 글 번호 추출 (항목별 고유 external_id용, 중복 행 방지)
                no_text = None
                try:
                    q = parse_qs(urlparse(full_url).query)
                    for key in ("articleNo", "article_no", "no", "id"):
                        if q.get(key):
                            no_text = str(q[key][0])
                            break
                except Exception:
                    pass
                # 중복 방지
                if not any(link['url'] == full_url for link in links):
                    link = {"url": full_url}
                    link["no"] = no_text if no_text else "Post"  # 스키마 일관성: 없으면 기본값
                    links.append(link)

        return links

    except RequestException:
        raise
    except Exception:
        logger.exception("get_medicine_notice_links parsing error list_url=%s", list_url)
        return []

# ==============================================================================
# [3] 상세 페이지 수집 엔진 (Detail Crawler) - 기존 유지
# ==============================================================================

def scrape_medicine_detail(url):
    try:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. 제목
        title = "제목 없음"
        header = soup.find(class_="article-header")
        if isinstance(header, Tag):
            # h1~h4 중 하나
            t_tag = header.find(['h1', 'h2', 'h3', 'h4'])
            if t_tag is not None and isinstance(t_tag, Tag):
                title = t_tag.get_text(strip=True)
            else:
                title = header.get_text(strip=True)

        # 2. 게시일
        date = "날짜 없음"
        # 헤더 텍스트 전체에서 날짜 패턴 검색
        d_text = header.get_text() if isinstance(header, Tag) else soup.get_text()
        d_match = re.search(r'\d{4}[.-]\s*\d{1,2}[.-]\s*\d{1,2}', d_text)
        if d_match:
            date = normalize_date(d_match.group())

        # 3. 본문 (HTML 구조 보존)
        content_html = ""
        fr_view = soup.find('div', class_='fr-view')

        if isinstance(fr_view, Tag):
            # 주석(키워드/태그) 기준으로 뒷부분 잘라내기
            end_comment = fr_view.find(string=lambda t: isinstance(t, Comment) and "키워드/태그" in t)
            if end_comment:
                # 주석부터 뒤의 형제들 모두 삭제
                curr: PageElement | None = end_comment
                while curr:
                    nxt = curr.next_sibling
                    curr.extract()
                    curr = nxt

            # HTML 정제 (이미지 제거, 표 보존)
            content_html = clean_html_content(fr_view)
        else:
            content_html = "(본문 영역 .fr-view를 찾을 수 없습니다)"

        # 4. 이미지 (본문에서 추출)
        images = []
        if isinstance(fr_view, Tag):
            # 원본 soup에서 이미지 태그 탐색 (clean_html_content는 복사본을 썼으므로)
            # 안전하게 다시 찾기
            raw_view = soup.find('div', class_='fr-view')
            if raw_view and isinstance(raw_view, Tag):
                for img in raw_view.find_all('img'):
                    if not isinstance(img, Tag):
                        continue
                    raw_src = img.get('src', '')
                    src = raw_src if isinstance(raw_src, str) else ''
                    if not src:
                        continue

                    if src.startswith('data:image'):
                        try:
                            head, enc = src.split(',', 1)
                            ext = "png"
                            if "jpeg" in head:
                                ext = "jpg"
                            images.append({"type":"base64", "data":enc, "name":f"img.{ext}"})
                        except Exception:
                            continue
                    else:
                        if any(x in src for x in ['icon', 'btn', 'blank']):
                            continue
                        full_url = urljoin(url, src)
                        fname = os.path.basename(full_url.split('?')[0])
                        if not fname or '.' not in fname:
                            fname = "image.jpg"

                        # 중복 방지
                        if not any(d['data'] == full_url for d in images if d['type']=='url'):
                            images.append({"type":"url", "data":full_url, "name":fname})

        # 5. 첨부파일
        attachments = []
        attach_div = soup.find('div', class_='attach-files')
        if attach_div and isinstance(attach_div, Tag):
            for a in attach_div.find_all('a'):
                if not isinstance(a, Tag):
                    continue
                raw_href = a.get('href', '')
                href = raw_href if isinstance(raw_href, str) else ''
                # 다운로드 링크 식별
                if 'download' in href or 'mode=download' in href:
                    fname = a.get_text(strip=True)
                    if fname and fname not in attachments:
                        attachments.append(fname)

        return title, date, content_html, images, attachments

    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_medicine_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_medicine_notice_links_async(client: httpx.AsyncClient, list_url: str):
    try:
        text = await fetch_html_async(client, list_url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        items = [t for t in soup.find_all("div", class_="bbs-item") if isinstance(t, Tag)]
        if not items:
            fallback = soup.select(".bbs-list li") or soup.select("tbody tr")
            items = [t for t in fallback if isinstance(t, Tag)]
        for item in items:
            if not isinstance(item, Tag):
                continue
            a_tag = item.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = a_tag.get("href", "") or ""
            if "articleNo" in href or "mode=view" in href:
                full_url = urljoin(list_url, href)
                no_text = None
                try:
                    q = parse_qs(urlparse(full_url).query)
                    for key in ("articleNo", "article_no", "no", "id"):
                        if q.get(key):
                            no_text = str(q[key][0])
                            break
                except Exception:
                    pass
                if not any(link["url"] == full_url for link in links):
                    links.append({"url": full_url, "no": no_text if no_text else "Post"})
        return links
    except Exception:
        logger.exception("get_medicine_notice_links_async parsing error list_url=%s", list_url)
        return []


async def scrape_medicine_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        title = "제목 없음"
        header = soup.find(class_="article-header")
        if isinstance(header, Tag):
            t_tag = header.find(["h1", "h2", "h3", "h4"])
            if isinstance(t_tag, Tag):
                title = t_tag.get_text(strip=True)
            else:
                title = header.get_text(strip=True)
        date = "날짜 없음"
        d_text = header.get_text() if isinstance(header, Tag) else soup.get_text()
        d_match = re.search(r"\d{4}[.-]\s*\d{1,2}[.-]\s*\d{1,2}", d_text)
        if d_match:
            date = normalize_date(d_match.group())
        content_html = ""
        fr_view = soup.find("div", class_="fr-view")
        if isinstance(fr_view, Tag):
            end_comment = fr_view.find(string=lambda t: isinstance(t, Comment) and "키워드/태그" in t)
            if end_comment:
                curr = end_comment
                while curr:
                    nxt = curr.next_sibling
                    curr.extract()
                    curr = nxt
            content_html = clean_html_content(fr_view)
        else:
            content_html = "(본문 영역 .fr-view를 찾을 수 없습니다)"
        images = []
        raw_view = soup.find("div", class_="fr-view")
        if raw_view and isinstance(raw_view, Tag):
            for img in raw_view.find_all("img"):
                if not isinstance(img, Tag):
                    continue
                src = img.get("src", "") or ""
                if not src:
                    continue
                if src.startswith("data:image"):
                    try:
                        head, enc = src.split(",", 1)
                        ext = "jpg" if "jpeg" in head else "png"
                        images.append({"type": "base64", "data": enc, "name": f"img.{ext}"})
                    except Exception:
                        continue
                else:
                    if any(x in src for x in ["icon", "btn", "blank"]):
                        continue
                    full_url = urljoin(url, src)
                    fname = os.path.basename(full_url.split("?")[0]) or "image.jpg"
                    if not any(d.get("data") == full_url for d in images if d.get("type") == "url"):
                        images.append({"type": "url", "data": full_url, "name": fname})
        attachments = []
        attach_div = soup.find("div", class_="attach-files")
        if attach_div and isinstance(attach_div, Tag):
            for a in attach_div.find_all("a"):
                if not isinstance(a, Tag):
                    continue
                href = a.get("href", "") or ""
                if "download" in href or "mode=download" in href:
                    fname = a.get_text(strip=True)
                    if fname and fname not in attachments:
                        attachments.append(fname)
        return title, date, content_html, images, attachments
    except Exception as e:
        logger.exception("scrape_medicine_detail_async error url=%s", url)
        raise
