"""
특정 단과대·기간 공지 삭제 후 재수집용.
재수집: POST /internal/trigger-crawl?college_code=<code> (보안 키 필수).
로컬: 프로젝트 루트에서 python scripts/delete_notices_for_rerun.py --college=engineering
"""
import argparse
import os
import sys
from datetime import datetime

# 프로젝트 루트 (스크립트 디렉터리의 상위)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from app.core.database_sync import get_sync_session, init_sync_db
from app.models.college import College
from app.models.notice import Notice


def main():
    parser = argparse.ArgumentParser(description="Delete notices for re-crawl (by college, optional date range).")
    parser.add_argument("--college", required=True, help="college_code (e.g. engineering)")
    parser.add_argument(
        "--before",
        help="Delete notices created_at < this date (YYYY-MM-DD). Optional.",
    )
    parser.add_argument(
        "--after",
        help="Delete notices created_at > this date (YYYY-MM-DD). Optional.",
    )
    args = parser.parse_args()

    init_sync_db()
    with get_sync_session() as session:
        row = session.execute(
            select(College).where(College.external_id == args.college).limit(1)
        ).scalar_one_or_none()
        if not row:
            print(f"College not found: {args.college}")
            sys.exit(1)
        college_id = row.id

        stmt = delete(Notice).where(Notice.college_id == college_id)
        if args.before:
            try:
                before_dt = datetime.strptime(args.before, "%Y-%m-%d")
                stmt = stmt.where(Notice.created_at < before_dt)
            except ValueError:
                print("--before must be YYYY-MM-DD")
                sys.exit(1)
        if args.after:
            try:
                after_dt = datetime.strptime(args.after, "%Y-%m-%d")
                stmt = stmt.where(Notice.created_at > after_dt)
            except ValueError:
                print("--after must be YYYY-MM-DD")
                sys.exit(1)

        result = session.execute(stmt)
        session.commit()
        deleted = result.rowcount
    print(f"Deleted {deleted} notice(s) for college={args.college}.")
    print("Re-crawl: POST <BACKEND_URL>/internal/trigger-crawl?college_code=" + args.college + " (header X-Crawl-Trigger-Secret or Authorization: Bearer <secret>)")


if __name__ == "__main__":
    main()
