"""
크롤러 설정 (사이트별 URL, 선택자, 규칙).
CAUTIONS: 코드를 수정하지 않고 config만 수정하여 대응 가능하도록 설계.
college.external_id(또는 college_code) -> config 키(모듈명) 매핑. 디스패처에서 사용.
레지스트리 패턴: get_crawler(module_name)으로 (get_links_fn, scrape_fn) 반환.
크롤러 모듈은 지연 임포트(순환 임포트 회피).
"""

import importlib
from collections.abc import Callable
from typing import Any

# 데이터센터 IP·WAF 차단 완화: 실제 Chrome 브라우저 User-Agent 사용. Python 기본 UA 사용 금지.
CRAWLER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# College.external_id 값 -> CRAWLER_CONFIG 키(모듈명). 시드/DB와 맞추면 됨.
COLLEGE_CODE_TO_MODULE: dict[str, str] = {
    "engineering": "yonsei_engineering",
    "science": "yonsei_science",
    "medicine": "yonsei_medicine",
    "ai": "yonsei_ai",
    "glc": "yonsei_glc",
    "underwood": "yonsei_underwood",
    "business": "yonsei_business",
}

# college별 "모듈명" = 파일명(import 경로와 일치). 예: from app.services.crawlers import yonsei_engineering
CRAWLER_CONFIG: dict[str, dict[str, Any]] = {
    "yonsei_engineering": {
        "name": "공과대학",
        "url": "https://engineering.yonsei.ac.kr/engineering/board/notice.do?mode=list&articleLimit=10",
        "get_links": "get_notice_links",
        "scrape_detail": "scrape_yonsei_engineering_precise",
        "type": "TYPE_A_LIST_NUM",
        "selectors": {"row": "tbody tr", "link": "a"},
    },
    # 나머지 단과대: url·get_links·scrape_detail은 크롤러 모듈과 일치.
    "yonsei_science": {
        "name": "이과대학",
        "url": "http://science.yonsei.ac.kr/community/notice",
        "get_links": "get_science_links",
        "scrape_detail": "scrape_science_detail",
    },
    "yonsei_medicine": {
        "name": "의과대학",
        "url": "https://medicine.yonsei.ac.kr/medicine/news/notice.do",
        "get_links": "get_medicine_notice_links",
        "scrape_detail": "scrape_medicine_detail",
    },
    "yonsei_ai": {
        "name": "인공지능융합대학",
        "url": "https://computing.yonsei.ac.kr/bbs/board.php?bo_table=sub4_4",
        "get_links": "get_computing_notice_links",
        "scrape_detail": "scrape_computing_detail",
    },
    "yonsei_glc": {
        "name": "글로벌인재대학",
        "url": "https://glc.yonsei.ac.kr/notice/?mod=list",
        "get_links": "get_glc_links",
        "scrape_detail": "scrape_glc_detail",
    },
    "yonsei_underwood": {
        "name": "언더우드국제대학",
        "url": "https://uic.yonsei.ac.kr/main/news.php?mid=m06_01_02",
        "get_links": "get_uic_links",
        "scrape_detail": "scrape_uic_detail",
    },
    "yonsei_business": {
        "name": "경영대학",
        "url": "https://ysb.yonsei.ac.kr/board.asp?mid=m06_01",
        "get_links": "get_business_notice_links",
        "scrape_detail": "scrape_business_detail",
    },
}


def get_crawler(module_name: str) -> tuple[Callable[..., list], Callable[..., tuple]]:
    """
    CRAWLER_CONFIG 기준으로 (get_links_fn, scrape_detail_fn) 반환.
    크롤러 모듈은 지연 임포트(순환 임포트 회피). crawl_service는 이 함수만 사용.
    """
    config = CRAWLER_CONFIG.get(module_name)
    if not config:
        raise ValueError(f"No crawler config for module: {module_name}")
    get_links_name = config.get("get_links") or "get_notice_links"
    scrape_name = config.get("scrape_detail") or "scrape_detail"
    mod = importlib.import_module(f"app.services.crawlers.{module_name}")
    get_links_fn = getattr(mod, get_links_name, None)
    scrape_fn = getattr(mod, scrape_name, None)
    if not get_links_fn or not scrape_fn:
        raise ValueError(f"Module {module_name} missing {get_links_name} or {scrape_name}")
    return (get_links_fn, scrape_fn)
