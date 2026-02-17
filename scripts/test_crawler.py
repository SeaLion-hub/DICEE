import asyncio
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.append(os.getcwd())

from app.core import database
from app.services.crawlers.yonsei_engineering import YonseiEngineeringCrawler

async def main():
    database.init_db()
    print("🕷️ 크롤러 테스트 시작...")
    
    if not database.async_session_maker:
        print("❌ DB 세션 생성 실패. .env 설정을 확인하세요.")
        return

    async with database.async_session_maker() as session:
        crawler = YonseiEngineeringCrawler(session)
        await crawler.run()
    
    print("✅ 테스트 종료!")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())