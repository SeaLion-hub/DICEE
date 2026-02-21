import logging
import os
import re
import urllib.parse
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag
from requests.exceptions import RequestException

from app.core.crawl_http import HtmlTooLargeError, fetch_html, fetch_html_async

logger = logging.getLogger(__name__)

# ================================================================================
# [1] 유틸리티 함수
# ================================================================================
def normalize_date(date_str):
    """문자열에서 시간 등을 무시하고 YYYY.MM.DD 형식만 정확히 뽑아냅니다."""
    try:
        match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning("normalize_date failed (format change?): date_str=%r", date_str[:100] if date_str else None)
        return date_str

# ================================================================================
# [2] GLC 리스트 페이지 크롤링 엔진 (새로 추가됨)
# ================================================================================
def get_glc_links(url):
    """GLC 공지사항 목록에서 '공지'를 제외하고 숫자 번호를 가진 일반 글 링크만 추출합니다."""
    links = []
    try:
        html = fetch_html(url)
        soup = BeautifulSoup(html, 'html.parser')

        # KBoard 게시판의 목록 행(tr) 탐색
        rows = soup.find_all('tr')

        for row in rows:
            if not isinstance(row, Tag):
                continue
            # 1. 번호 칼럼 추출
            uid_td = row.find('td', class_='kboard-list-uid')
            if not uid_td or not isinstance(uid_td, Tag):
                continue

            uid_text = uid_td.get_text(strip=True)

            # ★ 필터링: 번호가 숫자가 아니면(예: '공지') 패스
            if not uid_text.isdigit():
                continue

            # 2. 제목 및 링크 추출
            title_td = row.find('td', class_='kboard-list-title')
            if title_td and isinstance(title_td, Tag):
                a_tag = title_td.find('a')
                if a_tag and isinstance(a_tag, Tag):
                    href = a_tag.get('href')
                    if not href:
                        continue
                    full_url = urljoin(url, href)

                    # 제목 텍스트 (kboard-default-cut-strings <div> 안의 텍스트 추출)
                    title_div = a_tag.find('div', class_='kboard-default-cut-strings')
                    title = title_div.get_text(strip=True) if isinstance(title_div, Tag) else a_tag.get_text(strip=True)

                    links.append({
                        "no": uid_text,
                        "title": title,
                        "url": full_url
                    })
        return links
    except HtmlTooLargeError:
        logger.warning("get_glc_links HTML too large: url=%s", url[:200] if url else "")
        return []
    except RequestException:
        raise
    except Exception:
        logger.exception("get_glc_links parsing error url=%s", url)
        return []

# ================================================================================
# [3] GLC 상세 페이지 크롤링 엔진 (기존 로직 유지)
# ================================================================================
def scrape_glc_detail(url):
    try:
        html = fetch_html(url)
        soup = BeautifulSoup(html, 'html.parser')

        # 1. 제목 추출
        title = "제목 없음"
        title_div = soup.find('div', class_='kboard-title')
        if title_div and isinstance(title_div, Tag):
            h1_tag = title_div.find('h1')
            if isinstance(h1_tag, Tag):
                title = h1_tag.get_text(strip=True)

        # 2. 작성일 추출
        date = "날짜 없음"
        date_div = soup.find('div', class_='detail-date')
        if date_div and isinstance(date_div, Tag):
            val_div = date_div.find('div', class_='detail-value')
            if isinstance(val_div, Tag):
                date = normalize_date(val_div.get_text(strip=True))

        # 3. 본문 및 4. 이미지 추출
        content_html = ""
        images = []

        content_div = soup.find('div', class_='content-view')

        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all('img')):
                if not isinstance(img, Tag):
                    continue
                raw_src = img.get('data-orig-src') or img.get('src', '')
                src = raw_src if isinstance(raw_src, str) else ''
                if src and not any(x in src for x in ['icon', 'btn', 'blank']):
                    if src.startswith('data:image'):
                        try:
                            header, encoded = src.split(',', 1)
                            ext = "png"
                            if "jpeg" in header or "jpg" in header:
                                ext = "jpg"
                            images.append({"type": "base64", "data": encoded, "name": f"image_{idx+1}.{ext}"})
                        except Exception:
                            pass
                    else:
                        full_url = urljoin(url, src)
                        parsed = urllib.parse.urlparse(full_url)
                        encoded_path = urllib.parse.quote(parsed.path)
                        safe_url = urllib.parse.urlunparse(
                            (parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment)
                        )
                        fname = os.path.basename(parsed.path)
                        if not any(d.get('data') == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname or f"image_{idx+1}.jpg"})

                img.decompose()

            for table in content_div.find_all('table'):
                if isinstance(table, Tag) and not table.get('border'):
                    table['border'] = "1"

            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        # 5. 첨부파일 추출
        attachments = []
        buttons = soup.find_all('button', class_=lambda c: c and 'kboard-button-download' in c)
        for btn in buttons:
            if not isinstance(btn, Tag):
                continue
            fname = btn.get_text(strip=True)
            if fname and fname not in attachments:
                attachments.append(fname)

        return title, date, content_html, images, attachments

    except HtmlTooLargeError:
        logger.warning("scrape_glc_detail HTML too large: url=%s", url[:200] if url else "")
        return "제목 없음", "날짜 없음", "", [], []
    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_glc_detail parsing error url=%s, error=%s", url, e)
        raise


async def get_glc_links_async(client: httpx.AsyncClient, url: str):
    links = []
    try:
        html = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all("tr"):
            if not isinstance(row, Tag):
                continue
            uid_td = row.find("td", class_="kboard-list-uid")
            if not uid_td or not isinstance(uid_td, Tag):
                continue
            uid_text = uid_td.get_text(strip=True)
            if not uid_text.isdigit():
                continue
            title_td = row.find("td", class_="kboard-list-title")
            if title_td and isinstance(title_td, Tag):
                a_tag = title_td.find("a")
                if a_tag and isinstance(a_tag, Tag) and a_tag.get("href"):
                    full_url = urljoin(url, a_tag.get("href"))
                    title_div = a_tag.find("div", class_="kboard-default-cut-strings")
                    title = title_div.get_text(strip=True) if isinstance(title_div, Tag) else a_tag.get_text(strip=True)
                    links.append({"no": uid_text, "title": title, "url": full_url})
        return links
    except Exception:
        logger.exception("get_glc_links_async parsing error url=%s", url)
        return []


async def scrape_glc_detail_async(client: httpx.AsyncClient, url: str):
    try:
        html = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(html, "html.parser")
        title = "제목 없음"
        title_div = soup.find("div", class_="kboard-title")
        if title_div and isinstance(title_div, Tag):
            h1 = title_div.find("h1")
            if isinstance(h1, Tag):
                title = h1.get_text(strip=True)
        date = "날짜 없음"
        date_div = soup.find("div", class_="detail-date")
        if date_div and isinstance(date_div, Tag):
            val_div = date_div.find("div", class_="detail-value")
            if isinstance(val_div, Tag):
                date = normalize_date(val_div.get_text(strip=True))
        content_html = ""
        images = []
        content_div = soup.find("div", class_="content-view")
        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all("img")):
                if not isinstance(img, Tag):
                    continue
                src = (img.get("data-orig-src") or img.get("src")) or ""
                if src and not any(x in src for x in ["icon", "btn", "blank"]):
                    if src.startswith("data:image"):
                        try:
                            header, encoded = src.split(",", 1)
                            ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
                            images.append({"type": "base64", "data": encoded, "name": f"image_{idx+1}.{ext}"})
                        except Exception:
                            pass
                    else:
                        full_url = urljoin(url, src)
                        parsed = urllib.parse.urlparse(full_url)
                        enc_path = urllib.parse.quote(parsed.path)
                        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, enc_path, parsed.params, parsed.query, parsed.fragment))
                        fname = os.path.basename(parsed.path) or f"image_{idx+1}.jpg"
                        if not any(d.get("data") == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname})
                img.decompose()
            for table in content_div.find_all("table"):
                if isinstance(table, Tag) and not table.get("border"):
                    table["border"] = "1"
            content_html = content_div.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"
        attachments = []
        for btn in soup.find_all("button", class_=lambda c: c and "kboard-button-download" in c):
            if isinstance(btn, Tag):
                fname = btn.get_text(strip=True)
                if fname and fname not in attachments:
                    attachments.append(fname)
        return title, date, content_html, images, attachments
    except Exception as e:
        logger.exception("scrape_glc_detail_async error url=%s", url)
        raise
