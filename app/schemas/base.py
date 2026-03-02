"""공통 Pydantic 베이스·타입. 스키마 일관성·검증 강화."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """공통 model_config: from_attributes, validate_assignment, str_strip_whitespace."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

IdType = Annotated[str, Field(..., min_length=1, max_length=64, description="Identifier")]
SlugType = Annotated[
    str,
    Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_-]+$",
        description="URL-safe slug",
    ),
]
NameType = Annotated[str, Field(..., min_length=1, max_length=255, description="Display name")]
