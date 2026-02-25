"""CrawlRun(크롤 실행 이력) 모델. 단과대별 크롤 성공/실패·적재 건수 기록."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CrawlRun(Base):
    """
    단과대 크롤 1회 실행 이력. GET /internal/crawl-stats용.

    스키마: 복합 PK (id, started_at). 파티셔닝/인덱스 설계 시 started_at 활용 가능.
    Repository 계약: 현재 생성 로직은 run_id(id)당 1행만 생성하며, 조회/갱신은 id 단독으로
    "해당 run의 유일한 행"을 찾는 전제를 둠. 동일 id로 복수 행을 넣지 않음.
    """

    __tablename__ = "crawl_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    college_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # running | success | failed
    notices_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
