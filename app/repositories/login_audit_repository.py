"""LoginAudit Repository. 명세 3.2: ip_hmac·ip_hmac_key_version만 저장."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

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


def create_login_audits_bulk_sync(session: Session, rows: list[dict[str, object]]) -> int:
    """Insert login audit rows in one statement. Plain IP must never be included."""
    if not rows:
        return 0
    now = datetime.now(UTC)
    values: list[dict[str, object]] = []
    for row in rows:
        values.append(
            {
                "ip_hmac": str(row["ip_hmac"]),
                "ip_hmac_key_version": str(row["ip_hmac_key_version"]),
                "user_id": row.get("user_id"),
                "provider": row.get("provider"),
                "created_at": row.get("created_at") or now,
            }
        )
    session.execute(insert(LoginAudit).values(values))
    session.flush()
    return len(values)
