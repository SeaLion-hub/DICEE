import logging
import os
import re
import urllib.parse
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from requests.exceptions import RequestException

from app.core.crawler_config import CRAWLER_HEADERS

logger = logging.getLogger(__name__)

# ================================================================================
# [1] 유틸리티 함수: 영문 날짜 포맷팅 (Feb 19, 2026 -> 2026.02.19)
# ================================================================================
def normalize_uic_date(date_str):
    try:
        months = {
            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
            'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
        }

        match = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})', date_str)
        if match:
            m_str, d_str, y_str = match.groups()
            m_num = months.get(m_str[:3].capitalize(), '01')
            return f"{y_str}.{m_num}.{d_str.zfill(2)}"

        match_kr = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', date_str)
        if match_kr:
            y, m, d = match_kr.groups()
            return f"{y}.{m.zfill(2)}.{d.zfill(2)}"

        return date_str
    except Exception:
        logger.warning("normalize_date failed (format change?): date_str=%r", date_str[:100] if date_str else None)
        return date_str

# ================================================================================
# [2] UIC 리스트 페이지 크롤링 엔진 (카테고리별 상위 5개 추출)
# ================================================================================
def get_uic_links(url):
    """UIC 메인 페이지의 divbox_half_news 박스 3개에서 각각 상위 5개의 링크를 추출합니다."""
    links = []
    try:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 사진에서 확인한 3개의 half box 모두 찾기
        half_boxes = soup.find_all('div', class_='divbox_half_news')

        idx = 1 # 가상의 글 번호 (화면 표시용)

        for box in half_boxes:
            if not isinstance(box, Tag):
                continue
            # 1. 카테고리 이름 추출 (예: Academic Affairs)
            category_span = box.find('span', class_='Text_26bk')
            category = category_span.get_text(strip=True) if isinstance(category_span, Tag) else "Notice"

            # 2. 박스 안의 뉴스 컨테이너 찾기
            newsbox = box.find('div', class_='newsbox')
            if not newsbox or not isinstance(newsbox, Tag):
                continue

            # 3. a 태그 찾기 (상위 5개만 제한)
            a_tags = newsbox.find_all('a')
            count = 0

            for a in a_tags:
                if count >= 5: # 5개를 꽉 채웠으면 다음 박스로 넘어감
                    break
                if not isinstance(a, Tag):
                    continue
                href = a.get('href')
                if not href:
                    continue

                full_url = urljoin(url, href)
                title = a.get_text(strip=True)

                # 빈 링크나 "more" 같은 버튼 제외
                if not title or title.lower() == 'more':
                    continue

                links.append({
                    "no": str(idx),
                    "title": f"[{category}] {title}", # 보기 좋게 카테고리 달아주기
                    "url": full_url
                })
                idx += 1
                count += 1

        return links
    except RequestException:
        raise
    except Exception:
        logger.exception("get_uic_links parsing error url=%s", url)
        return []

# ================================================================================
# [3] UIC 상세 페이지 크롤링 엔진 (기존 로직 유지)
# ================================================================================
def scrape_uic_detail(url):
    try:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        title = "제목 없음"
        title_div = soup.find('div', id='BoardViewTitle')
        if title_div and isinstance(title_div, Tag):
            title = title_div.get_text(strip=True)

        date = "날짜 없음"
        attachments = []

        board_adds = soup.find_all('div', id='BoardViewAdd')
        for b_add in board_adds:
            if not isinstance(b_add, Tag):
                continue
            text_content = b_add.get_text(strip=True)

            if 'Views:' in text_content or re.search(r'[A-Za-z]+\s+\d{1,2},\s+\d{4}', text_content):
                date = normalize_uic_date(text_content)

            a_tags = b_add.find_all('a')
            for a in a_tags:
                if not isinstance(a, Tag):
                    continue
                img = a.find('img')
                if img:
                    fname = a.get_text(separator=' ', strip=True).strip('"').strip()
                    fname = re.sub(r'\([\d.,]+\s*(KB|MB|GB|Bytes?)\)', '', fname, flags=re.IGNORECASE).strip()
                    if fname and fname not in attachments:
                        attachments.append(fname)

        content_html = ""
        images = []

        content_div = soup.find('div', id='BoardContent')

        if content_div and isinstance(content_div, Tag):
            for idx, img in enumerate(content_div.find_all('img')):
                if not isinstance(img, Tag):
                    continue
                raw_src = img.get('src', '')
                src = raw_src if isinstance(raw_src, str) else ''
                if src and not any(x in src for x in ['icon', 'btn', 'blank', 'ext_']):
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

        return title, date, content_html, images, attachments

    except RequestException:
        raise
    except Exception as e:
        logger.exception("scrape_uic_detail parsing error url=%s, error=%s", url, e)
        raise
