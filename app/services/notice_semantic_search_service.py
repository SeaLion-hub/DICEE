"""공지 시맨틱 검색: 쿼리 텍스트 임베딩 후 벡터 검색. HTTP·schemas 없음."""

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
    limit: int = 20,
) -> list[Notice]:
    """
    단과대·게시 기간 내에서 쿼리와 코사인 거리가 가까운 공지를 반환한다.
    embedding이 NULL인 행은 제외된다.
    """
    q = (query or "").strip()
    if not q:
        raise EmptySemanticQueryError()

    ext = college_external_id.strip()
    college = await college_repository.get_by_external_id(session, ext)
    if college is None:
        raise UnknownCollegeExternalIdError(ext)

    lim = max(1, min(limit, 100))
    vec = await asyncio.to_thread(embed_text_sync, q)
    return await notice_repository.search_notices_by_embedding(
        session,
        college_id=college.id,
        published_from=published_from,
        published_to=published_to,
        query_embedding=vec,
        limit=lim,
    )


__all__ = ["search_public_notices_semantic"]
