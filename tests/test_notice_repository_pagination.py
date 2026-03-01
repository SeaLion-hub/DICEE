"""list_notices_paginated 커서 기반 페이징 및 인코딩/디코딩 단위 테스트."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.repositories.notice_repository import (
    _decode_cursor,
    _encode_cursor,
    list_notices_paginated,
)


def test_encode_decode_cursor_roundtrip() -> None:
    """_encode_cursor / _decode_cursor 왕복 시 동일 값 복원."""
    pub = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    created = datetime(2026, 3, 1, 11, 0, 0, tzinfo=UTC)
    nid = uuid4()
    encoded = _encode_cursor(pub, created, nid)
    assert encoded
    decoded = _decode_cursor(encoded)
    assert decoded is not None
    d_pub, d_created, d_nid = decoded
    assert d_pub == pub
    assert d_created == created
    assert d_nid == nid


def test_decode_cursor_none_or_empty_returns_none() -> None:
    """None 또는 빈 문자열은 None 반환."""
    assert _decode_cursor(None) is None
    assert _decode_cursor("") is None
    assert _decode_cursor("   ") is None


def test_decode_cursor_invalid_returns_none() -> None:
    """잘못된 base64/형식은 None 반환."""
    assert _decode_cursor("not-valid-base64!!!") is None
    assert _decode_cursor("YQ==") is None  # valid base64 but wrong format (single "a")


def test_encode_cursor_with_none_datetimes() -> None:
    """published_at/created_at이 None이어도 인코딩 가능."""
    nid = uuid4()
    encoded = _encode_cursor(None, None, nid)
    assert encoded
    decoded = _decode_cursor(encoded)
    assert decoded is not None
    assert decoded[0] is None
    assert decoded[1] is None
    assert decoded[2] == nid


@pytest.mark.asyncio
async def test_list_notices_paginated_returns_tuple() -> None:
    """list_notices_paginated 반환 타입이 (list[Notice], str | None) 임을 검증."""
    from unittest.mock import AsyncMock, MagicMock

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    rows, next_cursor = await list_notices_paginated(
        mock_session,
        limit=20,
        offset=0,
    )
    assert isinstance(rows, list)
    assert next_cursor is None
