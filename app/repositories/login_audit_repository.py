"""LoginAudit Repository. 명세 3.2: ip_hmac·ip_hmac_key_version만 저장."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.login_audit import LoginAudit


async def create_login_audit(
    session: AsyncSession,
    ip_hmac: str,
    ip_hmac_key_version: str,
    user_id: uuid.UUID | None = None,
    provider: str | None = None,
) -> None:
    """로그인 감사 1건 기록. 평문 IP 저장 금지."""
    stmt = insert(LoginAudit).values(
        ip_hmac=ip_hmac,
        ip_hmac_key_version=ip_hmac_key_version,
        user_id=user_id,
        provider=provider,
        created_at=datetime.now(UTC),
    )
    await session.execute(stmt)
    await session.flush()
