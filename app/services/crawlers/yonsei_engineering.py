import logging
import re
import os
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

    # --- [app2.py 로직] HTML 표 및 텍스트 구조 보존 ---
    def process_table_html(self, table_tag):
        for tag in table_tag(['script', 'style', 'noscript', 'iframe']):
            tag.decompose()
        if not table_tag.get('border'):
            table_tag['border'] = "1"
        return str(table_tag)

    def get_text_structurally(self, element):
        text_content = ""
        if isinstance(element, NavigableString):
            return str(element)
        if element.name == 'table':
            return self.process_table_html(element)
        
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

    # --- 실행 진입점 ---
    async def run(self):
        logger.info(f"[{self.college_code}] 크롤링 시작 (Base64+URL 이미지 지원)...")

        # 1. 단과대 정보 조회
        stmt = select(College).where(College.external_id == self.college_code)
        result = await self.session.execute(stmt)
        college = result.scalar_one_or_none()

        if not college:
            logger.error(f"College not found: {self.college_code}")
            return

        college_db_id = college.id 

        # 2. 목록 가져오기
        async with httpx.AsyncClient(timeout=30.0) as client:
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

                # 번호 확인 (공지사항 필터링)
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
                
                detail_url = urljoin(self.config["url"], link_tag['href'])

                await self.parse_detail_and_save(client, detail_url, college_db_id, external_id)

    # --- 상세 페이지 파싱 ---
    async def parse_detail_and_save(self, client, url, college_id, external_id):
        try:
            res = await client.get(url)
            soup = BeautifulSoup(res.text, 'html.parser')

            # 1. 제목
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

            # 2. 날짜
            pub_date = None
            date_match = re.search(r'\d{4}[.-]\d{2}[.-]\d{2}', soup.get_text())
            if date_match:
                try:
                    date_str = date_match.group().replace('.', '-')
                    pub_date = datetime.strptime(date_str, "%Y-%m-%d")
                except: pass

            # 3. 본문 및 이미지 추출 (app2.py 로직)
            content_text = ""
            main_container = None
            images_data = [] # [NEW] 이미지 저장 리스트

            anchor_text = soup.find(string=lambda t: t and "게시글 내용" in t)
            if anchor_text:
                start_tag = anchor_text.find_parent(['dt', 'th', 'td'])
                if start_tag:
                    target_body = start_tag.find_next_sibling(['dd', 'td'])
                    if target_body:
                        main_container = target_body
                        
                        # (1) 쓰레기 요소 제거
                        garbage_selectors = ['.btn_area', '.btn-wrap', '#bo_v_share', 'ul.btn_bo_user', 'div.btn_confirm']
                        for selector in garbage_selectors:
                            for tag in main_container.select(selector):
                                tag.decompose()
                        
                        # (2) 이미지 추출 (Base64 & URL 모두 포함)
                        img_tags = main_container.find_all('img')
                        for idx, img in enumerate(img_tags):
                            src = img.get('src', '')
                            if not src: continue
                            
                            # [Type A] Base64 이미지
                            if src.startswith('data:image'):
                                try:
                                    # 메타데이터 추출 (확장자 등)
                                    header, encoded = src.split(',', 1)
                                    ext = "png"
                                    if "jpeg" in header or "jpg" in header: ext = "jpg"
                                    elif "gif" in header: ext = "gif"
                                    
                                    # JSON 저장용 구조 (app2.py 호환)
                                    # 주의: data는 'src' 전체 문자열(Data URI)을 저장하여 프론트에서 바로 src로 쓸 수 있게 함
                                    images_data.append({
                                        "type": "base64",
                                        "data": src, # 전체 Data URI 저장
                                        "ext": ext,
                                        "name": f"image_{idx+1}.{ext}"
                                    })
                                except:
                                    continue
                            
                            # [Type B] URL 이미지
                            else:
                                if any(x in src for x in ['icon', 'btn', 'button', 'search', 'blank']): continue
                                
                                full_url = urljoin(url, src)
                                # 중복 체크
                                if any(d.get('data') == full_url for d in images_data if d['type'] == 'url'): continue
                                
                                file_name = img.get('data-file_name') or os.path.basename(src.split('?')[0])
                                if not file_name or '.' not in file_name: 
                                    file_name = f"image_{idx+1}.jpg"
                                    
                                images_data.append({
                                    "type": "url",
                                    "data": full_url,
                                    "ext": file_name.split('.')[-1],
                                    "name": file_name
                                })

                        # (3) 텍스트 추출
                        raw_text = self.get_text_structurally(main_container)
                        stop_keywords = ["관리자 if문", "답변글 버튼", "목록 List 버튼", "등록 버튼"]
                        for keyword in stop_keywords:
                            if keyword in raw_text:
                                raw_text = raw_text.split(keyword)[0]     
                        content_text = self.finalize_text(raw_text)

            if not content_text:
                content_text = "(본문 내용을 찾지 못했습니다)"

            # 4. 첨부파일
            attachments = []
            attach_labels = soup.find_all(string=re.compile("첨부"))
            for label in attach_labels:
                parent_row = label.find_parent(['tr', 'li', 'div', 'dl', 'dt', 'dd'])
                if parent_row and parent_row.name == 'dt':
                    parent_row = parent_row.find_next_sibling('dd')
                if parent_row:
                    links = parent_row.find_all('a')
                    for link in links:
                        file_name = link.get_text(strip=True)
                        href = link.get('href', '')
                        if href and not href.startswith('#') and 'javascript' not in href:
                             full_href = urljoin(url, href)
                             if not any(a['url'] == full_href for a in attachments):
                                 attachments.append({"name": file_name, "url": full_href})

            # DB 저장
            new_notice = Notice(
                college_id=college_id,
                external_id=external_id,
                title=title,
                raw_html=content_text,
                url=url,
                published_at=pub_date,
                images=images_data,      # [핵심] Base64 + URL 모두 저장된 리스트
                attachments=attachments, 
            )
            self.session.add(new_notice)
            await self.session.commit()
            
            logger.info(f"✅ Saved: [{external_id}] {title[:20]}... (Img:{len(images_data)} | File:{len(attachments)})")

        except Exception as e:
            logger.error(f"Failed to parse {url}: {e}")
            await self.session.rollback()