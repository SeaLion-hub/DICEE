# 크롤러·DB 네이밍 및 드라이버 검증 요약

전체 코드베이스에서 함수/변수명 일관성 및 DB 드라이버(psycopg only) 사용 여부를 점검한 결과.

---

## 1. 함수·변수명 일관성

### 1.1 크롤러 스펙·콜러블 이름

- **스펙 필드명**(모든 모듈 공통): `get_links`, `scrape_detail`  
  - `CrawlerModuleSpec`·`CRAWLER_CONFIG`에서 **콜러블 이름 문자열**을 저장하는 키.
- **실제 콜러블 이름**(모듈별 상이):  
  - 예: `get_chemistry_links`, `scrape_chemistry_detail` / `get_notice_links`, `scrape_yonsei_engineering_precise` 등.  
  - 각 크롤러 모듈의 `CRAWLER_SPEC`에 `get_links="함수명"`, `scrape_detail="함수명"` 형태로 지정.
- **crawler_config**: `spec.get_links`, `spec.scrape_detail`로 **스펙에 저장된 이름**을 읽어 `getattr(mod, get_links)` 등으로 호출.  
  → 스펙과 모듈 실제 함수명이 일치하므로 동작 일관됨.

### 1.2 seed_colleges.py

- `get_seed_colleges_from_crawlers()` 사용 (crawler_config에서 제공).
- 반환값 `(display_name, college_code)` → `CollegeSeed(name=..., external_id=...)`로 매핑.  
  - DB/모델: `College.external_id` = 크롤러의 `college_code`.  
  → 네이밍 일관됨.

### 1.3 테스트

- **test_crawler_discovery.py**:  
  - 스펙 예시로 `get_links="get_notice_links"`, `scrape_detail="scrape_detail"` 사용.  
  - 목 모듈에 `mod.get_notice_links`, `mod.scrape_detail` 부여 → discovery가 **스펙에 적힌 이름**으로 콜러블을 찾는 동작을 검증.  
  → 의도에 맞는 테스트.
- **test_tasks_and_config.py (validate_crawler_contract)**:  
  - fake config에 `"get_links": "get_links"`, `"scrape_detail": "scrape_detail"` 사용.  
  - 더미 모듈에 `get_links` 메서드만 두고 `scrape_detail` 누락 → 누락 시 fail-fast 검증.  
  → 의도에 맞음.

### 1.4 college_code vs external_id

- **college_code**: API·트리거·크롤러 스펙·Celery 태스크 인자 등 **비즈니스/설정 용어**.
- **external_id**: `colleges` 테이블 컬럼 및 `College` 모델 필드명.  
- 시드/트리거 시: `college_code` 값이 그대로 `College.external_id`로 저장·조회됨.  
  → 같은 값을 다른 레이어에서 다른 이름으로 쓰는 것으로, 일관된 매핑 유지.

---

## 2. DB 드라이버: psycopg only

### 2.1 코드 사용 현황

| 위치 | 내용 |
|------|------|
| **requirements.txt** | `psycopg[binary]==3.3.2` 만 존재. **asyncpg 미포함.** |
| **import asyncpg / from asyncpg** | **전역 검색 결과 0건.** |
| **app/core/database.py** | `_async_database_url()`에서 `asyncpg` 포함 시 `postgresql+psycopg`로 치환. `create_async_engine`에 psycopg URL 사용. |
| **app/core/database_sync.py** | `postgresql+asyncpg` → `postgresql+psycopg` 변환 후 `create_engine`(동기). |
| **alembic/env.py, env.py** | 마이그레이션용 `postgresql+psycopg` + `psycopg.connect`만 사용. |

→ 런타임·마이그레이션 모두 **psycopg(psycopg3)만 사용**, asyncpg 드라이버는 사용하지 않음.

### 2.2 적용한 수정

- **app/services/tasks.py**  
  - 주석: `동기 DB(psycopg2)` → `동기 DB(psycopg)` 로 변경 (실제 사용 드라이버는 psycopg3).
- **app/core/config/base.py**  
  - `DATABASE_URL` 검증 실패 시 메시지:  
    `"Runtime uses psycopg only (asyncpg URL is converted to psycopg)."` 로 명시.

---

## 3. 결론

- **함수/변수명**: 동일 기능에 대해 서로 다른 이름이 혼용되는 버그 없음.  
  - 스펙 필드(`get_links`/`scrape_detail`), 콜러블 이름(모듈별), `college_code`↔`external_id` 매핑 모두 일관됨.
- **DB 드라이버**: 전 구간 **psycopg only**. asyncpg 패키지 미사용, URL이 asyncpg 형태로 들어와도 psycopg로 변환 후 사용.
