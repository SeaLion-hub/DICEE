"""AI 추출기 공유 타입(Instructor 클라이언트 Protocol, 토큰 사용량)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """LLM completion usage (prompt / completion / total token counts)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class InstructorExtractionClient(Protocol):
    """Instructor 래퍼: 구조화 `create` 호출."""

    def create(
        self,
        *,
        messages: list[dict[str, object]],
        response_model: type[TModel],
    ) -> TModel:
        ...
