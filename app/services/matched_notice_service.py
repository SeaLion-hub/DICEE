"""맞춤(매칭) 공지 목록. 키셋 페이지 위에서 필터."""

from __future__ import annotations

import uuid

from app.core.database import AsyncSessionLike
from app.core.exceptions import UserNotFoundError
from app.domain.contracts.notice_public_contracts import NoticePublicListItemDTO
from app.repositories import notice_repository, user_repository
from app.services import matching_service
from app.services.user_profile_service import profile_from_user_profile_json


async def list_matched_notices(
    session: AsyncSessionLike,
    user_id: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
) -> tuple[list[NoticePublicListItemDTO], str | None, bool]:
    """
    매칭된 공지 목록. requires_profile=True이면 items 비움.

    매칭 밀도가 낮을 때 여러 번 list_notices_paginated를 호출할 수 있음(상한 반복).
    """
    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError()
    profile = profile_from_user_profile_json(user.profile_json)
    if not matching_service.matching_eligible(profile):
        return [], None, True

    out: list[NoticePublicListItemDTO] = []
    fetch_cursor = cursor
    batch_limit = min(max(limit * 4, limit + 10), 50)
    max_rounds = 40
    last_matched_notice_id: uuid.UUID | None = None
    last_pub = None
    last_created = None

    for _ in range(max_rounds):
        if len(out) >= limit:
            break
        rows, repo_next = await notice_repository.list_notices_paginated(
            session,
            limit=batch_limit,
            offset=0,
            cursor=fetch_cursor,
            load_college=True,
        )
        if not rows:
            break
        for n in rows:
            if len(out) >= limit:
                break
            if matching_service.notice_row_matches_profile(
                ai_extracted_json=n.ai_extracted_json,
                profile=profile,
            ):
                college = n.college
                ext = college.external_id if college is not None else ""
                out.append(
                    NoticePublicListItemDTO(
                        id=n.id,
                        college_external_id=ext,
                        external_id=n.external_id,
                        title=n.title,
                        url=n.url,
                        published_at=n.published_at,
                    )
                )
                last_matched_notice_id = n.id
                last_pub = n.published_at
                last_created = n.created_at
        if len(out) >= limit:
            break
        if repo_next is None:
            break
        fetch_cursor = repo_next

    next_out: str | None = None
    if len(out) >= limit and last_matched_notice_id is not None:
        next_out = notice_repository.encode_notice_list_cursor(last_pub, last_created, last_matched_notice_id)

    return out, next_out, False
