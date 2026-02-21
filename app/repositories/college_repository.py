"""College Repository. DB 쿼리만 수행."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.college import College


async def get_by_external_id(
    session: AsyncSession, external_id: str
) -> College | None:
    """external_id로 단과대 1건 조회 (비동기)."""
    result = await session.execute(
        select(College).where(College.external_id == external_id)
    )
    return result.scalars().one_or_none()


def get_by_external_id_sync(session: Session, external_id: str) -> College | None:
    """external_id로 단과대 1건 조회 (동기, 워커용)."""
    result = session.execute(
        select(College).where(College.external_id == external_id)
    )
    return result.scalars().one_or_none()
