"""User 도메인 계약. Repository는 Pydantic/API 스키마에 의존하지 않고 이 타입만 사용."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.user import User


@dataclass(frozen=True)
class UserUpsertCmd:
    """User upsert 입력. OAuth 프로필 등에서 서비스 계층이 구성해 Repository에 전달."""

    provider: str
    provider_user_id: str
    email: str | None
    name: str | None
    profile_json: dict[str, Any] | None


@dataclass(frozen=True)
class UserRecord:
    """User 조회 최소 정보. 향후 Repository 반환을 User 대신 이 타입으로 좁힐 때 사용."""

    id: UUID
    refresh_token_version: int


class UserRepositoryPort(Protocol):
    """User 저장소 포트. Session은 호출자(서비스)가 소유하고 인자로 전달(실용적 포트)."""

    async def upsert_by_provider_uid(self, session: AsyncSession, cmd: UserUpsertCmd) -> User: ...
