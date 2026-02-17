"""College(단과대) 모델."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.notice import Notice


class College(Base):
    """단과대/게시판 소스."""

    __tablename__ = "colleges"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    notices: Mapped[list["Notice"]] = relationship("Notice", back_populates="college")
