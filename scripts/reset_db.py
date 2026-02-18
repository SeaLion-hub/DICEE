# scripts/reset_db.py
import asyncio
import sys
import os

# 모듈 경로 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import async_session_maker

# 윈도우 환경 asyncio 에러 방지
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def reset_database():
    print("🧨 DB 초기화를 시작합니다 (DROP SCHEMA public)...")
    
    async with async_session_maker() as session:
        try:
            # DB 스키마를 통째로 날리고 다시 만듭니다. (가장 확실한 방법)
            await session.execute(text("DROP SCHEMA public CASCADE;"))
            await session.execute(text("CREATE SCHEMA public;"))
            await session.commit()
            print("✅ DB가 완전히 초기화되었습니다.")
        except Exception as e:
            await session.rollback()
            print(f"❌ 초기화 실패: {e}")

if __name__ == "__main__":
    asyncio.run(reset_database())