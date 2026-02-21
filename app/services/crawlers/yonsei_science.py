import logging
import os
import re
import urllib.parse
from urllib.parse import urljoin

import httpx
import requests
from bs4 import BeautifulSoup, Comment, Tag
from requests.exceptions import RequestException

from app.core.crawler_config import CRAWLER_HEADERS
from app.core.crawl_http import fetch_html_async

logger = logging.getLogger(__name__)

# ================================================================================
# [1] 기존 이과대학 상세 크롤링 로직 (절대 수정 안 함, 원본 그대로)
# ================================================================================
def normalize_date(date_str):
    try:
        match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match:
            y, m, d = match.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"
        return date_str
    except Exception:
        logger.warning("normalize_date failed (format change?): date_str=%r", date_str[:100] if date_str else None)
        return date_str

def get_body_soup(soup):
    start_node = soup.find(string=lambda text: isinstance(text, Comment) and "게시물 내용" in text and "//" not in text)
    if not start_node:
        return None

    end_comment = soup.find(string=lambda text: isinstance(text, Comment) and "// 게시물 내용" in text)

    temp_html = ""
    curr = start_node.next_sibling
    while curr and curr != end_comment:
        temp_html += str(curr)
        curr = curr.next_sibling

    temp_soup = BeautifulSoup(temp_html, 'html.parser')

    files_div = temp_soup.find('div', class_='nxb-view__files')
    if files_div:
        for element in files_div.find_all_next():
            element.extract()
        files_div.extract()

    return temp_soup

def scrape_science_detail(url):
    try:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        title = "제목 없음"
        t_tag = soup.find('h3', class_='nxb-view__header-title')
        if t_tag:
            title = t_tag.get_text(strip=True)

        date = "날짜 없음"
        dt_tags = soup.find_all('div', class_='nxb-view__info-dt')
        for dt in dt_tags:
            if '작성일' in dt.get_text():
                dd = dt.find_next_sibling('div', class_='nxb-view__info-dd')
                if dd:
                    date = normalize_date(dd.get_text(strip=True))
                    break

        content_html = ""
        images = []

        temp_soup = get_body_soup(soup)
        if temp_soup:
            for idx, img in enumerate(temp_soup.find_all('img')):
                src = img.get('src', '')
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

            for table in temp_soup.find_all('table'):
                if not table.get('border'):
                    table['border'] = "1"
            content_html = temp_soup.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"

        attachments = []
        file_divs = soup.find_all('div', class_='file-name-area')
        for fdiv in file_divs:
            if not isinstance(fdiv, Tag):
                continue
            fname = "".join([node for node in fdiv.contents if isinstance(node, str)]).strip()
            if fname and fname not in attachments:
                attachments.append(fname)

        return title, date, content_html, images, attachments

    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_science_detail parsing error url=%s, error=%s", url, e)
        raise

# ================================================================================
# [2] 이과대학 리스트 페이지 크롤러 (절대 수정 안 함, 원본 그대로)
# ================================================================================
def get_science_links(url):
    links = []
    try:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        rows = soup.select('.nxb-list-table tbody tr')
        for row in rows:
            if not isinstance(row, Tag):
                continue
            num_td = row.find('td', class_='nxb-list-table__num')
            if not num_td or not isinstance(num_td, Tag):
                continue

            if num_td.find('i', class_='nxb-list-table__notice-icon'):
                continue

            num = num_td.get_text(strip=True)
            if not num.isdigit():
                continue

            title_td = row.find('td', class_='nxb-list-table__title')
            if title_td and isinstance(title_td, Tag):
                a_tag = title_td.find('a')
                if a_tag and isinstance(a_tag, Tag):
                    href = a_tag.get('href')
                    if not href:
                        continue
                    full_url = urljoin(url, href)
                    links.append({
                        "no": num,
                        "title": a_tag.get_text(strip=True),
                        "url": full_url
                    })
        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_science_links parsing error url=%s", url)
        return []


async def get_science_links_async(client: httpx.AsyncClient, url: str):
    links = []
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        rows = soup.select(".nxb-list-table tbody tr")
        for row in rows:
            if not isinstance(row, Tag):
                continue
            num_td = row.find("td", class_="nxb-list-table__num")
            if not num_td or not isinstance(num_td, Tag):
                continue
            if num_td.find("i", class_="nxb-list-table__notice-icon"):
                continue
            num = num_td.get_text(strip=True)
            if not num.isdigit():
                continue
            title_td = row.find("td", class_="nxb-list-table__title")
            if title_td and isinstance(title_td, Tag):
                a_tag = title_td.find("a")
                if a_tag and isinstance(a_tag, Tag):
                    href = a_tag.get("href")
                    if href:
                        full_url = urljoin(url, href)
                        links.append({"no": num, "title": a_tag.get_text(strip=True), "url": full_url})
        return links
    except Exception:
        logger.exception("get_science_links_async parsing error url=%s", url)
        return []


async def scrape_science_detail_async(client: httpx.AsyncClient, url: str):
    try:
        text = await fetch_html_async(client, url, timeout=10.0)
        soup = BeautifulSoup(text, "html.parser")
        title = "제목 없음"
        t_tag = soup.find("h3", class_="nxb-view__header-title")
        if t_tag:
            title = t_tag.get_text(strip=True)
        date = "날짜 없음"
        for dt in soup.find_all("div", class_="nxb-view__info-dt"):
            if "작성일" in dt.get_text():
                dd = dt.find_next_sibling("div", class_="nxb-view__info-dd")
                if dd:
                    date = normalize_date(dd.get_text(strip=True))
                    break
        content_html = ""
        images = []
        temp_soup = get_body_soup(soup)
        if temp_soup:
            for idx, img in enumerate(temp_soup.find_all("img")):
                src = img.get("src", "")
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
                        encoded_path = urllib.parse.quote(parsed.path)
                        safe_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))
                        fname = os.path.basename(parsed.path) or f"image_{idx+1}.jpg"
                        if not any(d.get("data") == safe_url for d in images):
                            images.append({"type": "url", "data": safe_url, "name": fname})
                img.decompose()
            for table in temp_soup.find_all("table"):
                if not table.get("border"):
                    table["border"] = "1"
            content_html = temp_soup.decode_contents().strip()
        else:
            content_html = "(본문 영역을 찾을 수 없습니다)"
        attachments = []
        for fdiv in soup.find_all("div", class_="file-name-area"):
            if not isinstance(fdiv, Tag):
                continue
            fname = "".join([node for node in fdiv.contents if isinstance(node, str)]).strip()
            if fname and fname not in attachments:
                attachments.append(fname)
        return title, date, content_html, images, attachments
    except Exception as e:
        logger.exception("scrape_science_detail_async error url=%s", url)
        raise
