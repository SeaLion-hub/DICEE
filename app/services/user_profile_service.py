"""유저 프로필(매칭용) 조회·갱신."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserNotFoundError
from app.domain.contracts.user_profile_matching_contracts import (
    UserMeResponse,
    UserProfileForMatching,
    UserProfileMatchingPatch,
)
from app.repositories import user_repository


def _matching_eligible(profile: UserProfileForMatching) -> bool:
    return bool(profile.department_codes) or bool(profile.grades)


def profile_from_user_profile_json(raw: dict[str, object] | None) -> UserProfileForMatching:
    if not raw:
        return UserProfileForMatching()
    return UserProfileForMatching.model_validate(raw)


async def get_me(session: AsyncSession, user_id: uuid.UUID) -> UserMeResponse:
    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError()
    profile = profile_from_user_profile_json(user.profile_json)
    return UserMeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        profile=profile,
        matching_eligible=_matching_eligible(profile),
    )


async def patch_me(session: AsyncSession, user_id: uuid.UUID, patch: UserProfileMatchingPatch) -> UserMeResponse:
    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError()
    current = profile_from_user_profile_json(user.profile_json)
    data = current.model_dump()
    if patch.schema_version is not None:
        data["schema_version"] = patch.schema_version
    if patch.department_codes is not None:
        data["department_codes"] = patch.department_codes
    if patch.grades is not None:
        data["grades"] = patch.grades
    if patch.display_name is not None:
        dn = patch.display_name.strip()
        data["display_name"] = dn if dn else None
    merged = UserProfileForMatching.model_validate(data)
    await user_repository.update_profile_json(session, user_id, merged.model_dump(mode="json"))
    return UserMeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        profile=merged,
        matching_eligible=_matching_eligible(merged),
    )
