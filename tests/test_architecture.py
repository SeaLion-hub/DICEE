"""아키텍처 규칙 검사. 명세: 메인 엔티티 PK는 UUID v7. CI에서 빌드 실패 강제."""

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID

from app.models.college import College
from app.models.notice import Notice
from app.models.user import User


def _pk_type_is_uuid(model: type) -> bool:
    """모델의 PK 컬럼 타입이 PostgreSQL UUID(as_uuid=True)인지 확인."""
    mapper = inspect(model)
    pk_cols = [mapper.get_property_by_column(c) for c in mapper.primary_key]
    if len(pk_cols) != 1:
        return False
    col = mapper.primary_key[0]
    return type(col.type) is UUID and getattr(col.type, "as_uuid", False) is True


@pytest.mark.parametrize("model", [Notice, College, User])
def test_main_entity_pk_is_uuid(model: type) -> None:
    """명세: Notice, College, User의 PK는 UUID v7. Integer PK 사용 시 CI 실패."""
    assert _pk_type_is_uuid(model), (
        f"{model.__name__}.id must be UUID (PG UUID as_uuid=True). "
        "See docs/decisions/database-spec.md."
    )
