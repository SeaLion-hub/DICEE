"""
Celery 워커가 실행할 작업(Task) 정의.
"""

import asyncio
import logging
from celery import shared_task
from app.core.database import async_session_maker, init_db
# 주의: 파일명은 yonsei_engineering.py지만 import는 .py 없이
from app.services.crawlers.yonsei_engineering import YonseiEngineeringCrawler

logger = logging.getLogger(__name__)

async def run_crawler_async(college_code: str):
    """비동기 크롤러 실행 로직"""
    if not async_session_maker:
        init_db()
    
    async with async_session_maker() as session:
        if college_code == "engineering":
            crawler = YonseiEngineeringCrawler(session)
            await crawler.run()
        else:
            logger.warning(f"지원하지 않는 단과대 코드입니다: {college_code}")

@shared_task(name="app.services.tasks.crawl_college_task")
def crawl_college_task(college_code: str):
    """Celery가 호출하는 동기 래퍼 함수"""
    logger.info(f"Task Started: Crawling {college_code}")
    try:
        asyncio.run(run_crawler_async(college_code))
        return f"Crawling {college_code} completed."
    except Exception as e:
        logger.error(f"Crawling failed: {e}")
        raise e