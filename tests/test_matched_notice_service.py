"""list_matched_notices: 저장소가 next_cursor를 주면 여러 배치로 매칭을 이어간다."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.domain.contracts.user_profile_matching_contracts import UserProfileForMatching
from app.models.user import User
from app.services.matched_notice_service import list_matched_notices


def _user_with_profile(uid: uuid.UUID) -> User:
    u = User()
    u.id = uid
    u.provider = "google"
    u.provider_user_id = "test-sub"
    u.profile_json = UserProfileForMatching(
        department_codes=["yu_college_engineering"],
        grades=["3"],
    ).model_dump(mode="json")
    return u


def _notice_row() -> MagicMock:
    n = MagicMock()
    n.id = uuid.uuid4()
    n.published_at = None
    n.created_at = None
    n.college = MagicMock()
    n.college.external_id = "eng"
    n.external_id = "ext"
    n.title = "t"
    n.url = None
    return n


@pytest.mark.asyncio
async def test_list_matched_notices_fetches_second_batch_when_repo_returns_next_cursor() -> None:
    """첫 배치에 매칭이 없고 repo_next가 있으면 두 번째 list_notices_paginated가 호출된다."""
    uid = uuid.uuid4()
    user = _user_with_profile(uid)

    batch_a = [_notice_row() for _ in range(12)]
    batch_b = [_notice_row(), _notice_row()]

    call_count = 0

    async def fake_list_paginated(_session, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (batch_a, "cursor-page-2")
        return (batch_b, None)

    match_calls = 0

    def fake_match(*_args, **_kwargs):
        nonlocal match_calls
        match_calls += 1
        return match_calls >= 13

    mock_session = AsyncMock()
    with (
        patch(
            "app.services.matched_notice_service.user_repository.get_by_id",
            new_callable=AsyncMock,
            return_value=user,
        ),
        patch(
            "app.services.matched_notice_service.notice_repository.list_notices_paginated",
            new_callable=AsyncMock,
            side_effect=fake_list_paginated,
        ),
        patch(
            "app.services.matched_notice_service.matching_service.notice_row_matches_profile",
            side_effect=fake_match,
        ),
    ):
        items, next_cursor, requires_profile = await list_matched_notices(
            mock_session,
            uid,
            limit=2,
            cursor=None,
        )

    assert requires_profile is False
    assert call_count == 2
    assert len(items) == 2
    assert next_cursor is not None
