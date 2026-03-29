"""DB college_sources + 레지스트리로 list_url·크롤러 모듈명 해석."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG, get_crawler
from app.models.college import College
from app.models.college_source import CollegeSource
from app.repositories.college_repository import get_by_external_id_sync as get_college_by_external_id_sync
from app.repositories.college_source_repository import ensure_primary_college_source_sync


def resolve_crawl_module_list_url_and_source_sync(
    session: Session,
    college_code: str,
) -> tuple[College, CollegeSource, str, str]:
    """
    반환: (college, source, module_name, list_url).
    crawler_engine_key는 CRAWLER_CONFIG 키(패키지 모듈명)여야 한다.
    """
    college = get_college_by_external_id_sync(session, college_code)
    if college is None:
        raise ValueError(f"College not found: {college_code}")
    src = ensure_primary_college_source_sync(session, college)
    module_name = (src.crawler_engine_key or "").strip()
    if not module_name or module_name not in CRAWLER_CONFIG:
        fallback = COLLEGE_CODE_TO_MODULE.get(college_code)
        if not fallback:
            raise ValueError(f"No crawler module for college: {college_code}")
        module_name = fallback
    cfg = CRAWLER_CONFIG[module_name]
    list_url = (src.list_url or "").strip() or str(cfg.get("url") or "")
    if not list_url:
        raise ValueError(f"No list url for module: {module_name}")
    return college, src, module_name, list_url


def get_crawler_callables_for_college_sync(session: Session, college_code: str):
    """(get_links_fn, scrape_fn, list_url, college, source) — 파이프라인 진입용."""
    college, _src, module_name, list_url = resolve_crawl_module_list_url_and_source_sync(session, college_code)
    get_links_fn, scrape_fn = get_crawler(module_name)
    return get_links_fn, scrape_fn, list_url, college, _src
