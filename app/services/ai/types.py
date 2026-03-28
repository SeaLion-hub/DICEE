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


def add_token_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    pt = int(a.prompt_tokens or 0) + int(b.prompt_tokens or 0)
    ct = int(a.completion_tokens or 0) + int(b.completion_tokens or 0)
    tt = int(a.total_tokens or 0) + int(b.total_tokens or 0)
    if tt == 0 and (pt or ct):
        tt = pt + ct
    return TokenUsage(prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)


@dataclass(frozen=True, slots=True)
class ExtractorCallStats:
    """Per-run extractor telemetry (vision gating, call count, resolved model)."""

    vision_used: bool = False
    vision_image_count: int = 0
    raw_image_url_count: int = 0
    llm_calls: int = 0
    model_id: str = ""
    escalated: bool = False


class InstructorExtractionClient(Protocol):
    """Instructor 래퍼: 구조화 `create` 호출."""

    def create(
        self,
        *,
        messages: list[dict[str, object]],
        response_model: type[TModel],
    ) -> TModel: ...
