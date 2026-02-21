"""User Repository. DB 쿼리만 수행."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    provider + provider_user_id로 유저 조회 후 없으면 생성, 있으면 업데이트.
    """
    user = await get_by_provider_uid(session, provider, provider_user_id)
    if user:
        user.email = data.email or user.email
        user.name = data.name or user.name
        if data.profile_json is not None:
            user.profile_json = data.profile_json
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    user = User(
        provider=provider,
        provider_user_id=provider_user_id,
        email=data.email,
        name=data.name,
        profile_json=data.profile_json,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
