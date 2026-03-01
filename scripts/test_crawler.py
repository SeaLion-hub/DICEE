"""크롤러 동기 경로 테스트. crawl_college_sync 사용 (Celery 워커와 동일 경로)."""

import os
import sys

sys.path.insert(0, os.getcwd())

from app.core.database_sync import get_sync_session, init_sync_db
from app.services.crawl_service import crawl_college_sync


def main():
    init_sync_db()
    print("🕷️ 크롤러 테스트 시작 (sync)...")

    with get_sync_session() as session:
        count, notice_ids = crawl_college_sync(session, "engineering")
        session.commit()
        print(f"✅ 공대 크롤 완료. Upsert된 공지 수: {count}, AI 대상 ID 수: {len(notice_ids)}")

    print("✅ 테스트 종료!")


if __name__ == "__main__":
    main()
