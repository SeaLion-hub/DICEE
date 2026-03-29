"""학과 카탈로그 로드. ADR user-notice-matching §2.1-A."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "department_catalog.json"


@lru_cache
def _raw_catalog() -> tuple[dict[str, Any], ...]:
    data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("department_catalog.json must be a JSON array")
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        label = str(item.get("label", "")).strip()
        if not code or not label:
            continue
        out.append({"code": code, "label": label})
    return tuple(out)


def department_options() -> list[dict[str, str]]:
    """OpenAPI/메타 API용 {code, label} 목록."""
    return [{"code": r["code"], "label": r["label"]} for r in _raw_catalog()]


def allowed_department_codes() -> frozenset[str]:
    return frozenset(r["code"] for r in _raw_catalog())


def code_to_label_map() -> dict[str, str]:
    return {r["code"]: r["label"] for r in _raw_catalog()}


def official_labels_for_department_codes(codes: list[str]) -> frozenset[str]:
    """매칭용 공식 라벨 집합(공백 정규화 전 원문 라벨)."""
    m = code_to_label_map()
    return frozenset(m[c] for c in codes if c in m)


@lru_cache
def all_department_labels() -> tuple[str, ...]:
    """카탈로그의 모든 공식 라벨(학과·단과대 등). 매칭 퍼지용."""
    return tuple(r["label"] for r in _raw_catalog())
