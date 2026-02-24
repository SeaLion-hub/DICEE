import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from app.core import database
from app.services.crawl_service import crawl_college


async def main():
    database.init_db()
    print("🕷️ 크롤러 테스트 시작...")

    if not database.async_session_maker:
        print("❌ DB 세션 생성 실패. .env 설정을 확인하세요.")
        return

    async with database.async_session_maker() as session:
        count = await crawl_college(session, "engineering")
        await session.commit()
        print(f"✅ 공대 크롤 완료. Upsert된 공지 수: {count}")

    print("✅ 테스트 종료!")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
