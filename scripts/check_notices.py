"""최근 Notice 5건 출력 (동기 DB). 로컬 검증용."""
import os
import sys

_src_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_src_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from sqlalchemy import select

from app.core.database_sync import get_sync_session, init_sync_db
from app.models.notice import Notice

init_sync_db()
with get_sync_session() as s:
    r = s.execute(select(Notice).order_by(Notice.created_at.desc()).limit(5))
    for row in r.scalars().all():
        print(row.id, (row.title[:50] if row.title else ""))
