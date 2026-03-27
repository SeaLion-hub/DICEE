"""공개 공지 조회. Repository만 사용, HTTP·schemas 없음."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import ReadOnlySessionWrapper
from app.domain.contracts.notice_public_contracts import NoticePublicDetailDTO, NoticePublicListItemDTO
from app.models.notice import Notice
from app.repositories import college_repository, notice_repository


class UnknownCollegeExternalIdError(Exception):
    """college_external_id 필터가 DB에 없을 때."""

    def __init__(self, external_id: str) -> None:
        self.external_id = external_id
        super().__init__(f"No college with external_id={external_id!r}")


def _notice_to_list_dto(notice: Notice) -> NoticePublicListItemDTO:
    college = notice.college
    ext = college.external_id if college is not None else ""
    return NoticePublicListItemDTO(
        id=notice.id,
        college_external_id=ext,
        external_id=notice.external_id,
        title=notice.title,
        url=notice.url,
        published_at=notice.published_at,
    )


def _notice_to_detail_dto(notice: Notice) -> NoticePublicDetailDTO:
    base = _notice_to_list_dto(notice)
    nc = notice.notice_content
    content_url = nc.content_url if nc is not None else None
    return NoticePublicDetailDTO(
        id=base.id,
        college_external_id=base.college_external_id,
        external_id=base.external_id,
        title=base.title,
        url=base.url,
        published_at=base.published_at,
        content_url=content_url,
        created_at=notice.created_at,
        updated_at=notice.updated_at,
    )


async def list_public_notices(
    session: AsyncSession | ReadOnlySessionWrapper,
    *,
    limit: int,
    offset: int,
    cursor: str | None,
    college_external_id: str | None,
) -> tuple[list[NoticePublicListItemDTO], str | None]:
    """
    공지 목록. college_external_id가 있으면 해당 단과대만; 없으면 전체.
    """
    college_uuid: uuid.UUID | None = None
    if college_external_id is not None and college_external_id.strip():
        stripped = college_external_id.strip()
        college = await college_repository.get_by_external_id(session, stripped)
        if college is None:
            raise UnknownCollegeExternalIdError(stripped)
        college_uuid = college.id

    rows, next_cursor = await notice_repository.list_notices_paginated(
        session,
        limit=limit,
        offset=offset,
        cursor=cursor,
        college_id=college_uuid,
        load_college=True,
        load_taxonomy_mappings=False,
    )
    return ([_notice_to_list_dto(n) for n in rows], next_cursor)


async def get_public_notice_by_id(
    session: AsyncSession | ReadOnlySessionWrapper,
    notice_id: uuid.UUID,
) -> NoticePublicDetailDTO | None:
    """공지 상세. 없으면 None."""
    notice = await notice_repository.get_notice_by_id_with_relations(session, notice_id)
    if notice is None:
        return None
    return _notice_to_detail_dto(notice)
