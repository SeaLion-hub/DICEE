"""User Repository. DB 쿼리만 수행."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserBase


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
