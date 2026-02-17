import logging
import re
from datetime import datetime
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup, NavigableString
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crawler_config import CRAWLER_CONFIG
from app.models.notice import Notice
from app.models.college import College

logger = logging.getLogger(__name__)

class YonseiEngineeringCrawler:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.config = CRAWLER_CONFIG["engineering"]
        self.college_code = "engineering"

    def get_text_structurally(self, element):
        """app2.py의 구조적 텍스트 추출 로직 (표 HTML 유지)"""
        text_content = ""
        if isinstance(element, NavigableString):
            return str(element)
        if element.name == 'table':
            for tag in element(['script', 'style', 'noscript', 'iframe']):
                tag.decompose()
            if not element.get('border'):
                element['border'] = "1"
            return str(element)
        for child in element.children:
            if child.name in ['script', 'style', 'noscript']: continue
            if child.name == 'br':
                text_content += '\n'
                continue
            child_text = self.get_text_structurally(child)
            block_tags = ['div', 'p', 'li', 'tr', 'h1', 'h2', 'h3', 'option', 'dd', 'dt']
            if child.name in block_tags:
                if child_text.strip() or "<table" in child_text:
                    text_content += "\n" + child_text.strip() + "\n"
            else:
                text_content += child_text
        return text_content

    def finalize_text(self, text):
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        return text.strip()

    async def run(self):
        logger.info(f"[{self.college_code}] 크롤링 시작...")

        stmt = select(College).where(College.external_id == self.college_code)
        result = await self.session.execute(stmt)
        college = result.scalar_one_or_none()

        if not college:
            logger.error(f"College not found: {self.college_code}")
            return

        college_db_id = college.id # rollback 시 만료 방지

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(self.config["url"])
                response.raise_for_status()
            except Exception as e:
                logger.error(f"목록 페이지 접속 실패: {e}")
                return

            soup = BeautifulSoup(response.text, 'html.parser')
            rows = soup.select(self.config["selectors"]["row"])

            for row in rows:
                cols = row.find_all('td')
                if not cols: continue

                num_text = cols[0].get_text(strip=True)
                if not num_text.isdigit(): continue
                
                external_id = num_text
                
                # 중복 확인
                stmt = select(Notice).where(
                    Notice.college_id == college_db_id, 
                    Notice.external_id == external_id
                )
                res = await self.session.execute(stmt)
                if res.scalar_one_or_none():
                    continue

                link_tag = row.find('a')
                if not link_tag or not link_tag.get('href'): continue
                
                # 목록 URL을 기준으로 상세 주소 결합
                detail_url = urljoin(self.config["url"], link_tag['href'])

                await self.parse_detail_and_save(client, detail_url, college_db_id, external_id)

    async def parse_detail_and_save(self, client, url, college_id, external_id):
        try:
            res = await client.get(url)
            soup = BeautifulSoup(res.text, 'html.parser')

            # [제목] app2.py 로직: '제목' 텍스트 라벨 검색
            title = "제목 없음"
            title_label = soup.find(string=lambda t: t and "제목" in t)
            if title_label:
                title_container = title_label.find_parent(['dt', 'th', 'td'])
                if title_container:
                    title_elem = title_container.find_next_sibling(['dd', 'td'])
                    if title_elem:
                        title = self.get_text_structurally(title_elem).strip()
            
            if title == "제목 없음":
                h3 = soup.find('h3')
                if h3: title = self.get_text_structurally(h3).strip()

            # [날짜] 정규식 추출
            date_match = re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', soup.get_text())
            pub_date = None
            if date_match:
                try:
                    pub_date = datetime.strptime(date_match.group().replace('.', '-'), "%Y-%m-%d")
                except: pass

            # [본문] app2.py 로직: '게시글 내용' 라벨 검색
            content_text = ""
            main_container = None
            anchor_text = soup.find(string=lambda t: t and "게시글 내용" in t)
            if anchor_text:
                start_tag = anchor_text.find_parent(['dt', 'th', 'td'])
                if start_tag:
                    main_container = start_tag.find_next_sibling(['dd', 'td'])
                    if main_container:
                        # 불필요 요소 제거
                        for g in main_container.select('.btn_area, .btn-wrap, #bo_v_share'):
                            g.decompose()
                        raw_text = self.get_text_structurally(main_container)
                        content_text = self.finalize_text(raw_text)

            # 이미지 추출
            images = []
            if main_container:
                for img in main_container.find_all('img'):
                    src = img.get('src', '')
                    if src and not src.startswith('data:'):
                        images.append(urljoin(url, src))

            new_notice = Notice(
                college_id=college_id,
                external_id=external_id,
                title=title,
                raw_html=content_text,
                url=url,
                published_at=pub_date,
                poster_image_url=images[0] if images else None,
            )
            self.session.add(new_notice)
            await self.session.commit()
            logger.info(f"✅ Saved: {external_id} - {title[:25]}...")

        except Exception as e:
            logger.error(f"Failed to parse {url}: {e}")
            await self.session.rollback()