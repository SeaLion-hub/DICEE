"""공개 시맨틱 검색: 쿼리 임베딩 후 벡터 유사도 조회."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.database import AsyncSessionLike
from app.core.exceptions import EmptySemanticQueryError
from app.models.notice import Notice
from app.repositories import college_repository, notice_repository
from app.services.gemini_text_embedding import embed_text_sync
from app.services.notice_public_service import UnknownCollegeExternalIdError


async def search_public_notices_semantic(
    session: AsyncSessionLike,
    *,
    college_external_id: str,
    published_from: datetime,
    published_to: datetime,
    query: str,
    limit: int,
) -> list[Notice]:
    stripped_q = (query or "").strip()
    if not stripped_q:
        raise EmptySemanticQueryError()

    ext = (college_external_id or "").strip()
    college = await college_repository.get_by_external_id(session, ext)
    if college is None:
        raise UnknownCollegeExternalIdError(ext)

    try:
        vec = await asyncio.to_thread(embed_text_sync, stripped_q)
    except ValueError as e:
        raise ValueError(str(e)) from e

    return await notice_repository.search_notices_by_embedding(
        session,
        college_id=college.id,
        published_from=published_from,
        published_to=published_to,
        query_embedding=vec,
        limit=limit,
    )
