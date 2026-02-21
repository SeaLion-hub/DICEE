import logging
import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx
import requests
from bs4 import BeautifulSoup, Tag
from requests.exceptions import RequestException

from app.core.crawler_config import CRAWLER_HEADERS
from app.core.crawl_http import HtmlTooLargeError, fetch_html, fetch_html_async

logger = logging.getLogger(__name__)

# ==============================================================================
# [1] 유틸리티 함수
# ==============================================================================

def normalize_date(date_str):
    """날짜 문자열을 YYYY.MM.DD로 표준화"""
    try:
        numbers = re.findall(r'\d+', date_str)
        if len(numbers) >= 3:
            y, m, d = numbers[:3]
            if len(y) == 2:
                y = "20" + y
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning("normalize_date failed (format change?): date_str=%r", date_str[:100] if date_str else None)
        return date_str

def clean_html_content(element: Tag) -> str:
    """HTML 본문 정제 (스크립트 제거, 표 보존, 하단 버튼 제거). 원본 보호를 위해 문자열로 깊은 복사."""
    element_copy = BeautifulSoup(str(element), 'html.parser')

    # 보안상 제거
    for tag in element_copy.find_all(['script', 'style', 'noscript', 'iframe', 'img']):
        tag.decompose()

    # 하단 목록/수정 버튼 영역 제거
    for tag in element_copy.find_all(id="boardicon"):
        tag.decompose()

    # 표 테두리 강제 적용
    for table in element_copy.find_all('table'):
        if not isinstance(table, Tag):
            continue
        if not table.get('border'):
            table['border'] = "1"

    return element_copy.decode_contents().strip()

# ==============================================================================
# [2] 목록 수집 엔진 (List Crawler)
# ==============================================================================

def get_business_notice_links(list_url):
    """
    경영대 게시판에서 <td class="Subject"> 내부의 링크만 수집
    """
    try:
        try:
            text = fetch_html(list_url, timeout=10, encoding="cp949")
        except HtmlTooLargeError as e:
            logger.warning("get_business_notice_links body too large list_url=%s: %s", list_url, e)
            return []
        except RequestException:
            return []
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        # 1. <td class="Subject"> 찾기
        subjects = soup.find_all('td', class_='Subject')

        if not subjects:
            # 대소문자 문제일 수 있으므로 소문자로도 시도
            subjects = soup.find_all('td', class_='subject')

        for td in subjects:
            if not isinstance(td, Tag):
                continue
            # 2. 링크(a) 태그 추출
            a_tag = td.find('a')
            if not a_tag or not isinstance(a_tag, Tag):
                continue

            href = a_tag.get('href', '')
            title_text = a_tag.get_text(strip=True)

            if href:
                full_url = urljoin(list_url, href)

                # 번호 추출 (Subject 바로 앞 td가 보통 번호임)
                # 이전 형제 태그 찾기
                prev_td = td.find_previous_sibling('td')
                no_text = ""
                if prev_td and isinstance(prev_td, Tag):
                    no_text = prev_td.get_text(strip=True)

                # ★ 숫자가 아닌 경우(예: '공지', 'Link' 등) 빈 문자열로 처리하여
                # _external_id_from_url이 url에서 idx를 파싱하도록 유도
                if not no_text.isdigit():
                    no_text = ""

                # 중복 방지 (set 기반 O(1))
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    links.append({
                        "no": no_text,
                        "url": full_url,
                        "title_hint": title_text # 디버깅용
                    })

        return links

    except RequestException:
        raise
    except Exception:
        logger.exception("get_business_notice_links parsing error list_url=%s", list_url)
        return []

# ==============================================================================
# [3] 상세 페이지 수집 엔진 (Detail Crawler) - app5.py 로직 계승
# ==============================================================================

def scrape_business_detail(url):
    try:
        try:
            text = fetch_html(url, timeout=10, encoding="cp949")
        except HtmlTooLargeError as e:
            logger.warning("scrape_business_detail body too large url=%s: %s", url, e)
            raise RequestException from e
        except RequestException:
            raise
        soup = BeautifulSoup(text, "html.parser")

        # 1. 제목
        title = "제목 없음"
        # BoardViewTitle ID 사용
        t_elem = soup.find(id="BoardViewTitle")
        if t_elem and isinstance(t_elem, Tag):
            title = t_elem.get_text(strip=True)
        else:
            h = soup.find(['h2', 'h3'])
            if isinstance(h, Tag):
                title = h.get_text(strip=True)

        # 2. 게시일
        date = "날짜 없음"
        info = soup.find(id="BoardViewAdd")
        if isinstance(info, Tag):
            txt = info.get_text()
            match = re.search(r'등록일\s*:\s*([\d.-]+)', txt)
            if match:
                date = normalize_date(match.group(1))
            else:
                m2 = re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', txt)
                if m2:
                    date = normalize_date(m2.group())

        # 3. 본문 (HTML 보존)
        content_html = ""
        container = soup.find('div', id='BoardContent')
        if container and isinstance(container, Tag):
            content_html = clean_html_content(container)
        else:
            content_html = "(본문 BoardContent를 찾을 수 없습니다)"

        # 4. 이미지
        images = []
        image_urls: set[str] = set()
        if isinstance(container, Tag):
            # 원본 soup 재사용 (clean_html_content는 복사본 사용했으므로)
            raw_cont = soup.find('div', id='BoardContent')
            if raw_cont and isinstance(raw_cont, Tag):
                for img in raw_cont.find_all('img'):
                    if not isinstance(img, Tag):
                        continue
                    raw_src = img.get('src', '')
                    img_src = raw_src if isinstance(raw_src, str) else ''
                    if not img_src:
                        continue

                    if img_src.startswith('data:image'):
                        try:
                            _header, enc = img_src.split(',', 1)
                            images.append({"type":"base64", "data":enc, "name":"img.png"})
                        except Exception:
                            continue
                    else:
                        if any(x in img_src for x in ['icon', 'btn', 'blank']):
                            continue
                        full_url_str = urljoin(url, img_src)
                        fname = os.path.basename(full_url_str.split('?')[0])
                        if not fname or '.' not in fname:
                            fname = "image.jpg"

                        if full_url_str not in image_urls:
                            image_urls.add(full_url_str)
                            images.append({"type":"url", "data":full_url_str, "name":fname})

        # 5. 첨부파일 (downloadfile.asp)
        attachments: list[str] = []
        attachment_names_set: set[str] = set()
        # 파일 영역이 따로 있거나(BoardViewFile) 본문 근처
        area = soup.find(id="BoardViewFile")
        container = area if (area is not None and isinstance(area, Tag)) else soup
        for a in container.find_all('a'):
            if not isinstance(a, Tag):
                continue
            raw_href = a.get('href', '')
            href = raw_href if isinstance(raw_href, str) else ''
            if 'downloadfile.asp' in href:
                fname = a.get_text(strip=True)
                if fname and fname not in attachment_names_set:
                    attachment_names_set.add(fname)
                    attachments.append(fname)

        return title, date, content_html, images, attachments

    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_business_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_business_notice_links_async(client: httpx.AsyncClient, list_url: str):
    try:
        text = await fetch_html_async(
            client, list_url, timeout=10.0, encoding="cp949"
        )
        soup = BeautifulSoup(text, "html.parser")
        links: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for td in soup.find_all("td", class_="Subject") or soup.find_all("td", class_="subject"):
            if not isinstance(td, Tag):
                continue
            a_tag = td.find("a")
            if not a_tag or not isinstance(a_tag, Tag):
                continue
            href = a_tag.get("href", "") or ""
            title_text = a_tag.get_text(strip=True)
            if href:
                full_url = urljoin(list_url, href)
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    prev_td = td.find_previous_sibling("td")
                    no_text = prev_td.get_text(strip=True) if isinstance(prev_td, Tag) else ""
                    if not no_text.isdigit():
                        no_text = ""
                    links.append({"no": no_text, "url": full_url, "title_hint": title_text})
        return links
    except HtmlTooLargeError as e:
        logger.warning("get_business_notice_links_async body too large list_url=%s: %s", list_url, e)
        return []
    except Exception:
        logger.exception("get_business_notice_links_async parsing error list_url=%s", list_url)
        return []


async def scrape_business_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0, encoding="cp949")
        soup = BeautifulSoup(text, "html.parser")
        title = "제목 없음"
        t_elem = soup.find(id="BoardViewTitle")
        if t_elem and isinstance(t_elem, Tag):
            title = t_elem.get_text(strip=True)
        else:
            h = soup.find(["h2", "h3"])
            if isinstance(h, Tag):
                title = h.get_text(strip=True)
        date = "날짜 없음"
        info = soup.find(id="BoardViewAdd")
        if isinstance(info, Tag):
            txt = info.get_text()
            m = re.search(r"등록일\s*:\s*([\d.-]+)", txt) or re.search(r"\d{4}[.-]\d{2}[.-]\d{2}", txt)
            if m:
                date = normalize_date(m.group(1) if m.lastindex else m.group())
        content_html = ""
        container = soup.find("div", id="BoardContent")
        if container and isinstance(container, Tag):
            content_html = clean_html_content(container)
        else:
            content_html = "(본문 BoardContent를 찾을 수 없습니다)"
        images = []
        image_urls_async: set[str] = set()
        raw_cont = soup.find("div", id="BoardContent")
        if raw_cont and isinstance(raw_cont, Tag):
            for img in raw_cont.find_all("img"):
                if not isinstance(img, Tag):
                    continue
                img_src = img.get("src", "") or ""
                if not img_src:
                    continue
                if img_src.startswith("data:image"):
                    try:
                        _, enc = img_src.split(",", 1)
                        images.append({"type": "base64", "data": enc, "name": "img.png"})
                    except Exception:
                        continue
                else:
                    if any(x in img_src for x in ["icon", "btn", "blank"]):
                        continue
                    full_url_str = urljoin(url, img_src)
                    if full_url_str not in image_urls_async:
                        image_urls_async.add(full_url_str)
                        fname = os.path.basename(full_url_str.split("?")[0]) or "image.jpg"
                        images.append({"type": "url", "data": full_url_str, "name": fname})
        attachments = []
        attachment_names_async: set[str] = set()
        area = soup.find(id="BoardViewFile")
        cont = area if isinstance(area, Tag) else soup
        for a in cont.find_all("a"):
            if not isinstance(a, Tag):
                continue
            href = a.get("href", "") or ""
            if "downloadfile.asp" in href:
                fname = a.get_text(strip=True)
                if fname and fname not in attachment_names_async:
                    attachment_names_async.add(fname)
                    attachments.append(fname)
        return title, date, content_html, images, attachments
    except HtmlTooLargeError as e:
        logger.warning("scrape_business_detail_async body too large url=%s: %s", url, e)
        return None, "본문 초과", None, [], []
    except Exception as e:
        logger.exception("scrape_business_detail_async error url=%s", url, exc_info=True)
        raise
