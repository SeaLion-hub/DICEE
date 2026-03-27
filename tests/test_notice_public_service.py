"""notice_public_service: Repository 패치로 서비스 단위 분기 고정."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.notice_public_service import (
    UnknownCollegeExternalIdError,
    get_public_notice_by_id,
    list_public_notices,
)


@pytest.mark.asyncio
async def test_list_public_notices_unknown_college_raises() -> None:
    session = AsyncMock()
    with patch(
        "app.services.notice_public_service.college_repository.get_by_external_id",
        new_callable=AsyncMock,
    ) as m_college:
        m_college.return_value = None
        with pytest.raises(UnknownCollegeExternalIdError) as ei:
            await list_public_notices(
                session,
                limit=10,
                offset=0,
                cursor=None,
                college_external_id="missing-college",
            )
        assert ei.value.external_id == "missing-college"


@pytest.mark.asyncio
async def test_list_public_notices_resolves_college_and_passes_college_id() -> None:
    session = AsyncMock()
    college_id = uuid.uuid4()
    college = MagicMock()
    college.id = college_id
    notice = MagicMock()
    notice.id = uuid.uuid4()
    notice.college = MagicMock()
    notice.college.external_id = "eng"
    notice.external_id = "e1"
    notice.title = "t"
    notice.url = None
    notice.published_at = None

    with patch(
        "app.services.notice_public_service.college_repository.get_by_external_id",
        new_callable=AsyncMock,
    ) as m_college:
        m_college.return_value = college
        with patch(
            "app.services.notice_public_service.notice_repository.list_notices_paginated",
            new_callable=AsyncMock,
        ) as m_list:
            m_list.return_value = ([notice], "c2")
            items, cursor = await list_public_notices(
                session,
                limit=10,
                offset=0,
                cursor=None,
                college_external_id=" eng ",
            )
            m_college.assert_awaited_once_with(session, "eng")
            m_list.assert_awaited_once()
            call_kw = m_list.await_args.kwargs
            assert call_kw["college_id"] == college_id
            assert cursor == "c2"
            assert len(items) == 1


@pytest.mark.asyncio
async def test_list_public_notices_whitespace_college_skips_lookup() -> None:
    session = AsyncMock()
    cid = uuid.uuid4()
    notice = MagicMock()
    notice.id = cid
    notice.college = MagicMock()
    notice.college.external_id = "eng"
    notice.external_id = "ext-1"
    notice.title = "t"
    notice.url = None
    notice.published_at = None

    with patch(
        "app.services.notice_public_service.college_repository.get_by_external_id",
        new_callable=AsyncMock,
    ) as m_college:
        with patch(
            "app.services.notice_public_service.notice_repository.list_notices_paginated",
            new_callable=AsyncMock,
        ) as m_list:
            m_list.return_value = ([notice], None)
            items, cursor = await list_public_notices(
                session,
                limit=5,
                offset=0,
                cursor=None,
                college_external_id="   ",
            )
            m_college.assert_not_awaited()
            m_list.assert_awaited_once()
            assert cursor is None
            assert len(items) == 1
            assert items[0].id == cid
            assert items[0].college_external_id == "eng"


@pytest.mark.asyncio
async def test_get_public_notice_by_id_returns_none_when_missing() -> None:
    session = AsyncMock()
    nid = uuid.uuid4()
    with patch(
        "app.services.notice_public_service.notice_repository.get_notice_by_id_with_relations",
        new_callable=AsyncMock,
    ) as m_get:
        m_get.return_value = None
        out = await get_public_notice_by_id(session, nid)
        assert out is None


@pytest.mark.asyncio
async def test_get_public_notice_by_id_maps_detail_with_content() -> None:
    session = AsyncMock()
    nid = uuid.uuid4()
    now = datetime.now(UTC)
    nc = MagicMock()
    nc.content_url = "https://cdn.example/blob"
    notice = MagicMock()
    notice.id = nid
    notice.college = MagicMock()
    notice.college.external_id = "eng"
    notice.external_id = "e1"
    notice.title = "Title"
    notice.url = "https://u"
    notice.published_at = now
    notice.created_at = now
    notice.updated_at = now
    notice.notice_content = nc

    with patch(
        "app.services.notice_public_service.notice_repository.get_notice_by_id_with_relations",
        new_callable=AsyncMock,
    ) as m_get:
        m_get.return_value = notice
        dto = await get_public_notice_by_id(session, nid)
        assert dto is not None
        assert dto.content_url == "https://cdn.example/blob"
        assert dto.title == "Title"


@pytest.mark.asyncio
async def test_get_public_notice_by_id_maps_detail_without_content() -> None:
    session = AsyncMock()
    nid = uuid.uuid4()
    now = datetime.now(UTC)
    notice = MagicMock()
    notice.id = nid
    notice.college = None
    notice.external_id = "e1"
    notice.title = "T"
    notice.url = None
    notice.published_at = None
    notice.created_at = now
    notice.updated_at = now
    notice.notice_content = None

    with patch(
        "app.services.notice_public_service.notice_repository.get_notice_by_id_with_relations",
        new_callable=AsyncMock,
    ) as m_get:
        m_get.return_value = notice
        dto = await get_public_notice_by_id(session, nid)
        assert dto is not None
        assert dto.college_external_id == ""
        assert dto.content_url is None
