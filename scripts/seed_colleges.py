import asyncio
import sys
import os

# 1. 경로 설정 (프로젝트 루트 인식)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

print(f"📍 [DEBUG] 현재 실행 위치(CWD): {os.getcwd()}")
print(f"📍 [DEBUG] 프로젝트 루트 경로: {project_root}")

# 2. .env 파일 직접 확인 (Pydantic 거치지 않고 확인)
env_path = os.path.join(os.getcwd(), '.env')
print(f"📍 [DEBUG] .env 파일 예상 경로: {env_path}")

if os.path.exists(env_path):
    print("✅ [DEBUG] .env 파일이 존재합니다!")
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith("DATABASE_URL"):
                # 비밀번호 마스킹 처리해서 출력
                safe_line = line.strip()
                if "@" in safe_line:
                    prefix, suffix = safe_line.split("@")
                    safe_line = f"{prefix.split(':')[0]}:****@{suffix}"
                print(f"👀 [DEBUG] 파일 내 DATABASE_URL: {safe_line}")
else:
    print("❌ [DEBUG] .env 파일을 찾을 수 없습니다! (경로를 확인하세요)")

# 3. 모듈 로드 및 설정 확인
try:
    from app.core.config import settings
    print(f"⚙️ [DEBUG] settings.database_url 값: {settings.database_url}")
    
    from app.core import database
    print("🔄 [DEBUG] DB 초기화(init_db) 시도 중...")
    database.init_db()
    
    if database.engine:
        print("✅ [DEBUG] Engine 생성 성공!")
        print(f"   -> 접속 URL: {database.engine.url}")
    else:
        print("❌ [DEBUG] Engine이 None입니다. (settings.database_url이 비어있을 확률 높음)")

except Exception as e:
    print(f"🔥 [DEBUG] 로드 중 치명적 에러 발생: {e}")
    import traceback
    traceback.print_exc()

# 4. (원래 로직) 시드 데이터 주입 시도
from sqlalchemy import select
from app.models.college import College

# external_id는 crawler_config.COLLEGE_CODE_TO_MODULE 키와 일치 (engineering, science, medicine, ai, glc, underwood, business).
COLLEGES_DATA = [
    {"name": "공과대학", "external_id": "engineering"},
    {"name": "이과대학", "external_id": "science"},
    {"name": "의과대학", "external_id": "medicine"},
    {"name": "인공지능융합대학", "external_id": "ai"},
    {"name": "글로벌인재대학", "external_id": "glc"},
    {"name": "언더우드국제대학", "external_id": "underwood"},
    {"name": "경영대학", "external_id": "business"},
]

async def seed_colleges():
    if not database.async_session_maker:
        print("\n🚫 [STOP] DB 세션이 없어 작업을 중단합니다.")
        return

    print("\n🌱 단과대 데이터 시딩 시작...")
    try:
        async with database.async_session_maker() as session:
            for data in COLLEGES_DATA:
                stmt = select(College).where(College.external_id == data["external_id"])
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    print(f"  ⚠️ Skip: {data['name']} ({data['external_id']})")
                else:
                    print(f"  ✅ Add: {data['name']} ({data['external_id']})")
                    new_college = College(name=data['name'], external_id=data['external_id'])
                    session.add(new_college)
            await session.commit()
        print("✨ 시딩 완료!")
    except Exception as e:
        print(f"🔥 [ERROR] DB 작업 중 오류: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed_colleges())