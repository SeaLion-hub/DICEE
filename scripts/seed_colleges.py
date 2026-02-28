import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core import database
from app.core.config import settings
from app.models.college import College


def _mask_db_url(raw: str | None) -> str:
    """DB URL에서 비밀번호를 마스킹한 문자열을 반환."""
    if not raw:
        return "<empty>"
    try:
        url = make_url(str(raw))
        password = "****" if url.password else None
        masked = url.set(password=password)
        return str(masked)
    except Exception:
        safe = str(raw)
        if "@" in safe:
            prefix, suffix = safe.split("@", 1)
            if ":" in prefix:
                scheme_and_user = prefix.rsplit(":", 1)[0]
                return f"{scheme_and_user}:****@{suffix}"
        return "<redacted>"


# 1. 경로 설정 (프로젝트 루트 인식)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

print(f"📍 [DEBUG] 현재 실행 위치(CWD): {os.getcwd()}")
print(f"📍 [DEBUG] 프로젝트 루트 경로: {project_root}")

# 2. .env 파일 직접 확인 (Pydantic 거치지 않고 확인)
env_path = os.path.join(os.getcwd(), ".env")
print(f"📍 [DEBUG] .env 파일 예상 경로: {env_path}")

if os.path.exists(env_path):
    print("✅ [DEBUG] .env 파일이 존재합니다!")
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("DATABASE_URL"):
                # 값만 파싱해서 마스킹
                value = ""
                if "=" in line:
                    _, value = line.strip().split("=", 1)
                masked = _mask_db_url(value)
                print(f"👀 [DEBUG] 파일 내 DATABASE_URL(마스킹): {masked}")
else:
    print("❌ [DEBUG] .env 파일을 찾을 수 없습니다! (경로를 확인하세요)")

# 3. 모듈 로드 및 설정 확인
try:
    masked_settings_url = _mask_db_url(settings.db.database_url)
    print(f"⚙️ [DEBUG] settings.db.database_url 값(마스킹): {masked_settings_url}")

    print("🔄 [DEBUG] DB 초기화(init_db) 시도 중...")
    database.init_db()

    if database.get_engine():
        print("✅ [DEBUG] Engine 생성 성공!")
        print(f"   -> 접속 URL(마스킹): {_mask_db_url(str(database.engine.url))}")
    else:
        print("❌ [DEBUG] Engine이 None입니다. (settings.db.database_url이 비어있을 확률 높음)")

except Exception as e:
    print(f"🔥 [DEBUG] 로드 중 치명적 에러 발생: {e}")
    import traceback

    traceback.print_exc()


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
    maker = database.get_async_session_maker()
    if not maker:
        print("\n🚫 [STOP] DB 세션이 없어 작업을 중단합니다.")
        return

    print("\n🌱 단과대 데이터 시딩 시작...")
    try:
        async with maker() as session:
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