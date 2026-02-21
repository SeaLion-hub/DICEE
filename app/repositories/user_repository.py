"""User Repository. DB 쿼리만 수행."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.user import User
from app.schemas.user import UserBase


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    """id로 유저 조회."""
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalars().one_or_none()


async def increment_refresh_token_version(
    session: AsyncSession, user_id: int
) -> None:
    """로그아웃/탈취 시 해당 유저의 모든 Refresh 토큰 무효화."""
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(refresh_token_version=User.refresh_token_version + 1)
    )


async def get_by_provider_uid(
    session: AsyncSession, provider: str, provider_user_id: str
) -> User | None:
    """provider + provider_user_id로 유저 조회."""
    result = await session.execute(
        select(User).where(
            User.provider == provider,
            User.provider_user_id == provider_user_id,
        )
    )
    return result.scalars().one_or_none()


async def upsert_by_provider_uid(
    session: AsyncSession, provider: str, provider_user_id: str, data: UserBase
) -> User:
    """
    INSERT ... ON CONFLICT (provider, provider_user_id) DO UPDATE.
    동시 로그인 시 레이스 컨디션 없이 단일 쿼리로 처리.
    """
    now = datetime.now(UTC)
    base = pg_insert(User).values(
        provider=provider,
        provider_user_id=provider_user_id,
        email=data.email,
        name=data.name,
        profile_json=data.profile_json,
        refresh_token_version=0,
        created_at=now,
        updated_at=now,
    )
    stmt = base.on_conflict_do_update(
        constraint="uq_user_provider_uid",
        set_={
            User.email: func.coalesce(base.excluded.email, User.email),
            User.name: func.coalesce(base.excluded.name, User.name),
            User.profile_json: func.coalesce(base.excluded.profile_json, User.profile_json),
            User.updated_at: now,
        },
    ).returning(User.id)
    result = await session.execute(stmt)
    user_id = result.scalars().one()
    await session.flush()
    user = await session.get(User, user_id)
    if user is None:
        raise RuntimeError("User not found after upsert")
    return user
