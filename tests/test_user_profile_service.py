"""user_profile_service branch coverage for profile merge semantics."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.exceptions import UserNotFoundError
from app.domain.contracts.user_profile_matching_contracts import UserProfileMatchingPatch
from app.services.user_profile_service import get_me, patch_me, profile_from_user_profile_json


def _user(*, profile_json: dict[str, object] | None) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "student@example.com"
    user.name = "Student"
    user.profile_json = profile_json
    return user


def test_profile_from_user_profile_json_empty_returns_default_profile() -> None:
    assert profile_from_user_profile_json(None).model_dump() == {
        "schema_version": 1,
        "department_codes": [],
        "grades": [],
        "display_name": None,
    }
    assert profile_from_user_profile_json({}).department_codes == []


def test_profile_from_user_profile_json_validates_existing_json() -> None:
    profile = profile_from_user_profile_json(
        {
            "department_codes": ["yu_college_engineering"],
            "grades": ["3", "3"],
            "display_name": "  Alice  ",
            "ignored": "value",
        }
    )

    assert profile.department_codes == ["yu_college_engineering"]
    assert profile.grades == ["3"]
    assert profile.display_name == "Alice"


@pytest.mark.asyncio
async def test_get_me_missing_user_raises_user_not_found() -> None:
    session = AsyncMock()
    with patch("app.services.user_profile_service.user_repository.get_by_id", new_callable=AsyncMock) as get_by_id:
        get_by_id.return_value = None
        with pytest.raises(UserNotFoundError):
            await get_me(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_me_empty_profile_is_not_matching_eligible() -> None:
    session = AsyncMock()
    user = _user(profile_json=None)

    with patch("app.services.user_profile_service.user_repository.get_by_id", new_callable=AsyncMock) as get_by_id:
        get_by_id.return_value = user
        out = await get_me(session, user.id)

    assert out.id == user.id
    assert out.profile.department_codes == []
    assert out.profile.grades == []
    assert out.matching_eligible is False


@pytest.mark.asyncio
async def test_get_me_profile_with_department_or_grade_is_matching_eligible() -> None:
    session = AsyncMock()
    user = _user(profile_json={"department_codes": ["yu_college_engineering"], "grades": []})

    with patch("app.services.user_profile_service.user_repository.get_by_id", new_callable=AsyncMock) as get_by_id:
        get_by_id.return_value = user
        out = await get_me(session, user.id)

    assert out.profile.department_codes == ["yu_college_engineering"]
    assert out.matching_eligible is True


@pytest.mark.asyncio
async def test_patch_me_preserves_omitted_fields_and_updates_requested_fields() -> None:
    session = AsyncMock()
    user = _user(
        profile_json={
            "department_codes": ["yu_college_engineering"],
            "grades": ["2"],
            "display_name": "Existing",
        }
    )
    patch_body = UserProfileMatchingPatch(grades=["3"])

    with (
        patch("app.services.user_profile_service.user_repository.get_by_id", new_callable=AsyncMock) as get_by_id,
        patch(
            "app.services.user_profile_service.user_repository.update_profile_json",
            new_callable=AsyncMock,
        ) as update_profile_json,
    ):
        get_by_id.return_value = user
        out = await patch_me(session, user.id, patch_body)

    assert out.profile.department_codes == ["yu_college_engineering"]
    assert out.profile.grades == ["3"]
    assert out.profile.display_name == "Existing"
    assert out.matching_eligible is True
    update_profile_json.assert_awaited_once_with(
        session,
        user.id,
        {
            "schema_version": 1,
            "department_codes": ["yu_college_engineering"],
            "grades": ["3"],
            "display_name": "Existing",
        },
    )


@pytest.mark.asyncio
async def test_patch_me_blank_display_name_becomes_none() -> None:
    session = AsyncMock()
    user = _user(profile_json={"department_codes": [], "grades": ["1"], "display_name": "Old"})
    patch_body = UserProfileMatchingPatch(display_name="   ")

    with (
        patch("app.services.user_profile_service.user_repository.get_by_id", new_callable=AsyncMock) as get_by_id,
        patch(
            "app.services.user_profile_service.user_repository.update_profile_json",
            new_callable=AsyncMock,
        ) as update_profile_json,
    ):
        get_by_id.return_value = user
        out = await patch_me(session, user.id, patch_body)

    assert out.profile.display_name is None
    assert update_profile_json.await_args.args[2]["display_name"] is None


@pytest.mark.asyncio
async def test_patch_me_missing_user_raises_user_not_found() -> None:
    session = AsyncMock()
    with patch("app.services.user_profile_service.user_repository.get_by_id", new_callable=AsyncMock) as get_by_id:
        get_by_id.return_value = None
        with pytest.raises(UserNotFoundError):
            await patch_me(session, uuid.uuid4(), UserProfileMatchingPatch(grades=["3"]))
