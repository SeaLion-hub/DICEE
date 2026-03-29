"""공개 메타 API (학과·학년 옵션)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.domain.contracts.ai_extraction import TargetGrade
from app.domain.department_catalog import department_options

router = APIRouter(prefix="/meta", tags=["meta"])


class DepartmentOptionItem(BaseModel):
    code: str
    label: str


class DepartmentOptionsResponse(BaseModel):
    items: list[DepartmentOptionItem]


class GradeOptionItem(BaseModel):
    value: str
    label: str


class GradeOptionsResponse(BaseModel):
    items: list[GradeOptionItem]


_GRADE_LABELS: dict[str, str] = {
    TargetGrade.ONE.value: "1학년",
    TargetGrade.TWO.value: "2학년",
    TargetGrade.THREE.value: "3학년",
    TargetGrade.FOUR.value: "4학년",
    TargetGrade.FIVE.value: "5학년",
    TargetGrade.SIX.value: "6학년",
    TargetGrade.ALL.value: "전체 학년",
    TargetGrade.GRAD_MASTER.value: "석사",
    TargetGrade.GRAD_PHD.value: "박사",
    TargetGrade.GRAD_ALL.value: "대학원 전체",
    TargetGrade.OTHER.value: "기타",
}


@router.get("/department-options", response_model=DepartmentOptionsResponse)
async def list_department_options() -> DepartmentOptionsResponse:
    rows = department_options()
    return DepartmentOptionsResponse(items=[DepartmentOptionItem(**r) for r in rows])


@router.get("/grade-options", response_model=GradeOptionsResponse)
async def list_grade_options() -> GradeOptionsResponse:
    items = [GradeOptionItem(value=e.value, label=_GRADE_LABELS.get(e.value, e.value)) for e in TargetGrade]
    return GradeOptionsResponse(items=items)
