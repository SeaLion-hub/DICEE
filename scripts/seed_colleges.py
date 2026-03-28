"""
단과대(College) 시드 스크립트.

실행: 프로젝트 루트에서 python scripts/seed_colleges.py [--dry-run] [--verbose]
Import 시점 부작용을 피하기 위해 경로·env 보정 후 app을 로드하고, 실패 시 rollback 후 재전파·비영구 종료(exit 1).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 경로·env 보정은 반드시 app import보다 먼저
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(PROJECT_ROOT / ".env")

# 스크립트 단독 실행 시 Settings에 필요한 최소 env (필드가 없으면 기본값)
import os as _os

if "APP_ENTRY" not in _os.environ:
    _os.environ.setdefault("APP_ENTRY", "api")

from dataclasses import dataclass

from app.core import database
from app.core.config import settings
from app.core.crawler_config import get_seed_colleges_from_crawlers
from app.models.college import College
from sqlalchemy import select
from sqlalchemy.engine import make_url

logger = logging.getLogger("seed_colleges")


@dataclass(frozen=True, slots=True)
class CollegeSeed:
    name: str
    external_id: str


def _colleges_data() -> tuple[CollegeSeed, ...]:
    """크롤러 스펙에서 시드 소스 생성 (한 곳 수정으로 crawler 등록 + seed 동기화)."""
    rows = get_seed_colleges_from_crawlers()
    return tuple(CollegeSeed(name=name, external_id=external_id) for name, external_id in rows)


COLLEGES_DATA: tuple[CollegeSeed, ...] = _colleges_data()


def _mask_db_url(raw: str | None) -> str:
    if not raw:
        return "<empty>"
    try:
        url = make_url(str(raw))
        return str(url.set(password="****" if url.password else None))
    except Exception:
        return "<redacted>"


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


async def seed_colleges(*, dry_run: bool) -> tuple[int, int]:
    """기존 건 수, 삽입 건 수 반환. N+1 제거를 위해 external_id 일괄 조회 후 삽입."""
    database.init_db()
    maker = database.get_async_session_maker()
    if maker is None:
        raise RuntimeError("DB session maker is not initialized. Check DATABASE_URL.")

    target_ids = [c.external_id for c in COLLEGES_DATA]

    async with maker() as session:
        try:
            result = await session.execute(
                select(College.external_id).where(College.external_id.in_(target_ids))
            )
            existing_ids = set(result.scalars().all())

            to_insert = [c for c in COLLEGES_DATA if c.external_id not in existing_ids]
            for item in to_insert:
                session.add(College(name=item.name, external_id=item.external_id))

            if dry_run:
                await session.rollback()
            else:
                await session.commit()

            return (len(existing_ids), len(to_insert))
        except Exception:
            await session.rollback()
            raise


async def _run(dry_run: bool) -> int:
    raw_url = settings.db.database_url
    masked = _mask_db_url(raw_url)
    logger.info("Starting seed_colleges (database_url=%s, dry_run=%s)", masked, dry_run)

    existed, inserted = await seed_colleges(dry_run=dry_run)
    logger.info(
        "Seed finished (existing=%d, inserted=%d, dry_run=%s)",
        existed,
        inserted,
        dry_run,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed colleges into DB.")
    parser.add_argument("--dry-run", action="store_true", help="Do not commit changes.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _configure_logging(args.verbose)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        return asyncio.run(_run(dry_run=args.dry_run))
    except Exception:
        logger.exception("seed_colleges failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
