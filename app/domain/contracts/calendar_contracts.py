"""달력·유저 일정 입력/출력. services용 (schemas는 re-export)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCalendarEventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    notice_id: uuid.UUID
    title: str | None = Field(default=None, max_length=512)
    start_at: datetime
    end_at: datetime | None = None


class UserCalendarEventCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notice_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime | None = None
