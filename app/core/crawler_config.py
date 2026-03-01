"""
크롤러 설정 (사이트별 URL, 선택자, 규칙).
CAUTIONS: 코드를 수정하지 않고 config만 수정하여 대응 가능하도록 설계.
college.external_id(또는 college_code) -> config 키(모듈명) 매핑. 디스패처에서 사용.
레지스트리 패턴: CrawlerSpec 등록 → get_crawler(module_name)으로 (get_links_fn, scrape_fn) 반환.
Wave 6: 각 크롤러 모듈에 CRAWLER_SPEC 상수 두고 pkgutil로 자동 수집. 수집 결과는 college_code 기준 정렬(deterministic).
크롤러 모듈은 지연 임포트(순환 임포트 회피).
"""

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class CrawlerModuleSpec:
    """크롤러 모듈이 자기기술로 노출하는 스펙. college_code·display_name·list_url·get_links·scrape_detail 필수."""

    college_code: str
    display_name: str
    list_url: str
    get_links: str
    scrape_detail: str


@dataclass(frozen=True)
class CrawlerSpec:
    """크롤러 1건 스펙. 등록/검증/조회 분리용. name·module_name·url·get_links·scrape_detail 필수."""

    name: str
    module_name: str
    url: str
    get_links: str
    scrape_detail: str
    type: str = ""
    selectors: dict[str, Any] | None = None


# 데이터센터 IP·WAF 차단 완화: 실제 Chrome 브라우저 User-Agent 사용. Python 기본 UA 사용 금지.
CRAWLER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

def _discover_crawler_specs() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """
    app.services.crawlers 패키지에서 CRAWLER_SPEC을 가진 모듈을 수집.
    college_code 기준 정렬(deterministic). 중복 college_code·URL 비정상·callable 누락 시 fail-fast.
    """
    import app.services.crawlers as crawlers_pkg

    seen_codes: set[str] = set()
    specs: list[tuple[str, CrawlerModuleSpec]] = []

    for importer, modname, ispkg in pkgutil.iter_modules(crawlers_pkg.__path__, prefix=""):
        if ispkg or modname in ("base", "typing_helpers"):
            continue
        fullname = f"app.services.crawlers.{modname}"
        try:
            mod = importlib.import_module(fullname)
        except Exception as e:
            raise ValueError(
                f"Crawler module import failed: {fullname}. Fix or remove."
            ) from e
        spec = getattr(mod, "CRAWLER_SPEC", None)
        if not isinstance(spec, CrawlerModuleSpec):
            continue
        if spec.college_code in seen_codes:
            raise ValueError(
                f"Duplicate college_code: {spec.college_code} (module {modname}). "
                "Ensure each crawler has a unique college_code."
            )
        seen_codes.add(spec.college_code)
        if not (spec.list_url or "").strip():
            raise ValueError(
                f"Crawler {modname} CRAWLER_SPEC.list_url is empty. Set a valid list URL."
            )
        try:
            parsed = urlparse(spec.list_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("URL missing scheme or netloc")
        except Exception as e:
            raise ValueError(
                f"Crawler {modname} CRAWLER_SPEC.list_url invalid: {spec.list_url}"
            ) from e
        get_links = (spec.get_links or "").strip() or "get_notice_links"
        scrape_detail = (spec.scrape_detail or "").strip() or "scrape_detail"
        if not callable(getattr(mod, get_links, None)):
            raise ValueError(
                f"Crawler module {modname} missing callable: {get_links}. "
                f"Add {get_links} to {fullname}."
            )
        if not callable(getattr(mod, scrape_detail, None)):
            raise ValueError(
                f"Crawler module {modname} missing callable: {scrape_detail}. "
                f"Add {scrape_detail} to {fullname}."
            )
        specs.append((modname, spec))

    specs.sort(key=lambda x: x[1].college_code)
    college_to_module: dict[str, str] = {}
    config: dict[str, dict[str, Any]] = {}
    for modname, spec in specs:
        get_links = (spec.get_links or "").strip() or "get_notice_links"
        scrape_detail = (spec.scrape_detail or "").strip() or "scrape_detail"
        college_to_module[spec.college_code] = modname
        config[modname] = {
            "name": spec.display_name,
            "url": spec.list_url,
            "get_links": get_links,
            "scrape_detail": scrape_detail,
        }
    return (college_to_module, config)


_registry: tuple[dict[str, str], dict[str, dict[str, Any]]] | None = None


def _ensure_registry() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """지연 초기화: 첫 접근 시 discovery 실행(순환 임포트 회피)."""
    global _registry
    if _registry is None:
        _registry = _discover_crawler_specs()
    return _registry


def __getattr__(name: str) -> Any:
    """COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG 첫 접근 시 discovery 실행 후 반환."""
    if name == "COLLEGE_CODE_TO_MODULE":
        code_to_mod, _ = _ensure_registry()
        globals()["COLLEGE_CODE_TO_MODULE"] = code_to_mod
        return code_to_mod
    if name == "CRAWLER_CONFIG":
        _, config = _ensure_registry()
        globals()["CRAWLER_CONFIG"] = config
        return config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_seed_colleges_from_crawlers() -> list[tuple[str, str]]:
    """자동 수집된 크롤러 스펙에서 (display_name, college_code) 목록 반환. college_code 기준 정렬(deterministic)."""
    code_to_mod, config = _ensure_registry()
    return [
        (config[modname]["name"], college_code)
        for college_code, modname in sorted(code_to_mod.items(), key=lambda x: x[0])
    ]


def _crawler_callable_names(config: dict[str, Any]) -> tuple[str, str]:
    """registry 저장값 조회 시 strip 정규화(공백 문자열·불일치 방지)."""
    get_links_name = (config.get("get_links") or "get_notice_links").strip() or "get_notice_links"
    scrape_name = (config.get("scrape_detail") or "scrape_detail").strip() or "scrape_detail"
    return (get_links_name, scrape_name)


def get_crawler_spec(module_name: str) -> CrawlerSpec | None:
    """모듈명으로 CrawlerSpec 조회. 없으면 None."""
    _, config_dict = _ensure_registry()
    config = config_dict.get(module_name)
    if not config:
        return None
    return CrawlerSpec(
        name=config.get("name", ""),
        module_name=module_name,
        url=config.get("url", ""),
        get_links=config.get("get_links") or "get_notice_links",
        scrape_detail=config.get("scrape_detail") or "scrape_detail",
        type=config.get("type", ""),
        selectors=config.get("selectors"),
    )


def get_crawler(module_name: str) -> tuple[Callable[..., list], Callable[..., tuple]]:
    """
    CRAWLER_CONFIG(스펙) 기준으로 (get_links_fn, scrape_detail_fn) 반환. 동기용.
    크롤러 모듈은 지연 임포트(순환 임포트 회피).
    """
    spec = get_crawler_spec(module_name)
    if spec is None:
        raise ValueError(f"No crawler config for module: {module_name}")
    _, config_dict = _ensure_registry()
    config = config_dict[module_name]
    get_links_name, scrape_name = _crawler_callable_names(config)
    mod = importlib.import_module(f"app.services.crawlers.{module_name}")
    get_links_fn = getattr(mod, get_links_name, None)
    scrape_fn = getattr(mod, scrape_name, None)
    if not get_links_fn or not scrape_fn:
        missing = [
            n for n in (get_links_name, scrape_name) if not (getattr(mod, n, None) and callable(getattr(mod, n, None)))
        ]
        raise ValueError(
            f"Module {module_name} missing required callables: {', '.join(missing)}. "
            f"Add them to app.services.crawlers.{module_name}"
        )
    return (get_links_fn, scrape_fn)


def validate_crawler_contract() -> None:
    """
    CRAWLER_CONFIG에 등록된 모든 모듈이 sync 크롤러 함수(get_links, scrape_detail)를 갖는지 검증한다.
    누락 시 부팅 단계에서 fail-fast. (sync-only 계약.)
    """
    _, config_dict = _ensure_registry()
    for module_name, config in config_dict.items():
        try:
            mod = importlib.import_module(f"app.services.crawlers.{module_name}")
        except Exception as e:
            raise ValueError(
                f"Crawler module import failed: {module_name}. "
                f"Fix the module at app.services.crawlers.{module_name} or remove from CRAWLER_CONFIG."
            ) from e

        get_links_name, scrape_name = _crawler_callable_names(config)
        required = [get_links_name, scrape_name]
        missing = [name for name in required if not callable(getattr(mod, name, None))]
        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(
                f"Crawler module {module_name} missing required callables: {missing_str}. "
                f"Add {missing_str} to app.services.crawlers.{module_name}"
            )
