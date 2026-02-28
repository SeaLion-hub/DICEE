"""
아키텍처 계층 import 규칙 검사.
- app.api: app.repositories 직접 import 금지 (app.services, app.core, app.schemas, app.domain 허용).
- app.services: app.schemas import 금지 (app.repositories, app.domain, app.core 허용).
"""

from __future__ import annotations

import ast
from pathlib import Path


def _iter_py_modules(app_root: Path, subdir: str) -> list[tuple[Path, str]]:
    """app_root/subdir 아래 .py 파일을 (Path, app.subdir.xxx) 모듈명으로 나열."""
    result: list[tuple[Path, str]] = []
    package_path = app_root / subdir
    if not package_path.is_dir():
        return result
    for p in package_path.rglob("*.py"):
        if p.name.startswith("_"):
            continue
        rel = p.relative_to(app_root)
        parts = list(rel.parts[:-1]) + [rel.stem]
        mod = "app." + ".".join(parts)
        result.append((p, mod))
    return result


def _resolve_import_module(current_module: str, module: str | None, level: int) -> str | None:
    """Resolve absolute module for both absolute and relative imports."""
    if level <= 0:
        return module
    package_parts = current_module.split(".")[:-1]
    pops = max(0, level - 1)
    if pops > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - pops]
    if module:
        return ".".join([*base_parts, *module.split(".")])
    return ".".join(base_parts)


def _collect_imports_from_file(path: Path, current_module: str) -> list[str]:
    """파일에서 from x import y / import x 형태의 최상위 모듈명 수집."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    modules: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name == "app":
                    modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import_module(current_module, node.module, node.level)
            if not resolved:
                continue
            top = resolved.split(".")[0]
            if top == "app":
                modules.append(resolved)

    # "app.xxx" 형태만 남기고, app.api / app.services 등 패키지 레벨로 정규화
    out: list[str] = []
    for m in modules:
        if m == "app":
            out.append("app")
            continue
        if m.startswith("app."):
            parts = m.split(".")
            if len(parts) >= 2:
                out.append(f"app.{parts[1]}")
    return list(dict.fromkeys(out))


def test_api_does_not_import_repositories() -> None:
    """app.api 모듈은 app.repositories를 직접 import 하지 않는다."""
    app_root = Path(__file__).resolve().parents[1] / "app"
    violations: list[str] = []
    for path, mod in _iter_py_modules(app_root, "api"):
        for imp in _collect_imports_from_file(path, mod):
            if imp.startswith("app.repositories"):
                violations.append(f"{mod} imports {imp}")
    assert not violations, f"api must not import repositories: {violations}"


def test_services_does_not_import_schemas() -> None:
    """app.services 모듈은 app.schemas를 import 하지 않는다."""
    app_root = Path(__file__).resolve().parents[1] / "app"
    violations: list[str] = []
    for path, mod in _iter_py_modules(app_root, "services"):
        for imp in _collect_imports_from_file(path, mod):
            if imp.startswith("app.schemas"):
                violations.append(f"{mod} imports {imp}")
    assert not violations, f"services must not import schemas: {violations}"
