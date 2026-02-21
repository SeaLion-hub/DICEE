# 작업 로그 (WORK_LOG)

## 목차

- [작성 규칙](#작성-규칙)
- [작성 형식](#작성-형식)
- [2026-02-22](#2026-02-22)
- [2026-02-20](#2026-02-20)
- [2026-02-18](#2026-02-18)
- [2026-02-17](#2026-02-17)
- [2026-02-16](#2026-02-16)
- [템플릿 (새 날짜에 복사)](#템플릿-새-날짜에-복사)

---

## 작성 규칙

- 예정이 아니라 **실제로 한 수정**만 기록
- 가능하면 **파일/디렉터리**와 **이유/결과**를 1줄로 함께 남기기

## 작성 형식

- `- [단계 또는 영역] 무엇을 했는지 (어떤 파일/기능). 왜 또는 결과 한 줄.`

---

## 2026-02-21

- [문서] docs/ROADMAP.md — **테크 리드 로드맵 보완 지시** 반영. (1) **E1(OOM)**: 할 일에 **SQLAlchemy Identity Map 캐싱 방지를 위해 청크 commit 직후 반드시 session.expunge_all() 호출** 명시(리스트만 비우면 OOM 재발). (2) **S3(침묵하는 예외)**: "except Exception 금지"와 코드 불일치 해결 — **3단계 완료 전 필수 Hotfix** 블록 추가. Sentry capture 블록 내부의 except Exception을 sentry_sdk 전용 예외로 변경(Log Poisoning 방지). 미완 시 3단계 완료 선언 금지. (3) **Redis 분산 락**: 추가 검토 아이디어에 **좀비 락 방어** 제약 추가 — 타임아웃은 예상 크롤 완료 시간 + 20% 마진(예: 3~5분)으로 타이트하게, timeout=3600 금지. P1 요약에 expunge_all·Hotfix 반영.
- [3단계 P0/P1 기술부채 구현] **P0**: (1) **S1** app/core/config.py JWT_ISSUER·JWT_AUDIENCE 추가, auth_service create_jwt_pair에 iss·aud 클레임 추가, .env.example 갱신. (2) **S5/R1** app/schemas/auth.py GoogleTokenResponse 추가, auth_service exchange_google_code를 model_validate 검증·AuthError 반환으로 변경, google_login token_data.id_token 사용. (3) **A1** app/core/crawl_http.py fetch_html_async(httpx stream), crawler_config get_crawler_async, 7개 크롤러에 get_*_links_async·scrape_*_detail_async 추가, crawl_service crawl_college에서 asyncio.to_thread 제거·httpx.AsyncClient·get_crawler_async만 사용. (4) **A2** crawl_service에 _collect_payloads_sync·_collect_payloads_async 도입, crawl_college·crawl_college_sync는 수집 로직 공통화·진입점만 주입. **P1**: (5) **E1** crawl_college_sync에서 UPSERT_CHUNK_SIZE(50) 단위 upsert 후 session.commit()·**session.expunge_all()** 호출. (6) **O2** app/api/internal.py post_trigger_crawl를 async def로 변경, apply_async는 asyncio.to_thread로 실행, 실패 시 503·logger.exception. (7) **S4** _validate_trigger_secret에 secrets.compare_digest 사용. (8) **S3** crawl_service Sentry 래핑 except Exception: pass 제거, logger.warning(sentry_err)로 구체 처리.
- [문서] docs/ROADMAP.md — **기술 부채·품질 개선 계획** 최종 수정(계획 승인 반영). 점수·결론에 "PASS: 계획 승인 (Plan Approved)" 및 플랜 반려→재제출→승인 경과 추가. **최종 리뷰 평가 및 피드백** 섹션 추가: P0 "이제야 기본이 잡혔다"·P0 머지 전 새 기능 코드 금지, P1 "GC를 맹신하지 마라"·E1 코드 구현 검증·O2/S3 타협 없음, P2&P3 방어적 인프라·S2 requirements/CI 강제, 결론 "문서의 계획이 코드가 되기 전까지는 의미 없다"·P0 브랜치부터 작업·PR 시 코드 라인 단위 리뷰.
- [문서] docs/ROADMAP.md — **기술 부채·품질 개선 계획** 전면 재작성(플랜 반려 피드백 반영). (1) **P0(즉시 실행)**: A1 비동기 크롤러 전환·A2 DRY 플로우 공통화(아키텍처 버그로 상향), S1 JWT iss/aud·S5·R1 구글 응답 Pydantic(Auth 대문으로 상향). (2) **S2**: 인프라 원칙(DSN 있으면 sentry-sdk 설치 보장)·코드로 덮지 말 것, 방어 코드는 선택. (3) **S3**: except Exception 금지, sentry_sdk 관련 구체 예외만 처리. (4) **E1**: 청크뿐 아니라 **참조 해제(del/스코프 분리)** 강제 명시(GC는 참조 유지 시 해제 안 함). (5) **O2**: trigger-crawl 무조건 async def + 비동기 클라이언트, 타협 없음. (6) **우선순위 요약** P0/P1/P2/P3 재조정, 플랜 반려 요지·재보고 원칙 추가.
- [문서] docs/ROADMAP.md — **기술 부채·품질 개선 계획 (테크 리드 리뷰 반영)** 섹션 추가. 실리콘밸리 테크 리드 관점 코드 리뷰(아키텍처·보안·확장성·코드 가독성)에서 지적된 항목을 계획표로 상세 반영. (1) **아키텍처**: asyncio.to_thread 남용 → 비동기 크롤러(httpx/aiohttp), DRY(crawl_college vs crawl_college_sync) → 플로우 공통화·이중 진입점 일관성. (2) **보안**: JWT iss/aud 추가, main.py Sentry ImportError try/except, crawl_service Sentry 래핑 except Exception: pass → 로깅 유지, internal 시크릿 compare_digest, 구글 토큰 응답 Pydantic 검증. (3) **확장성**: notices 청크 단위 처리(OOM 방지), redirect_uri 설정화, 동기 DB 풀 설정화. (4) **코드 가독성**: 구글 응답 스키마·예외 정책 문서화·health status 명시. (5) **우선순위**: P0 Sentry main.py, P1 3단계 마무리(비동기·DRY·청크·Sentry 래핑·compare_digest), P2 2단계 보강(JWT·Pydantic·redirect_uri), P3 배포·정리 시. 목차에 링크 추가.
- [크롤 아키텍처·보안·확장성 개선 계획 반영] **(1단계)** crawl_service: _url_path_only_for_hash 추가, _external_id_from_url 해시 fallback 시 path만 사용. _parse_published_at·_external_id_from_url 파싱 실패 시 Sentry capture_exception/capture_message 의무화. crawl_college_sync 변수명 t_stripped→title_stripped. 6개 크롤러 normalize_date 내 except Exception 시 logger.warning 추가. DEPLOYMENT: 크롤 운영 정책(FastAPI 트리거는 개발/소량용·프로덕션은 Celery만), 첨부파일 저장 원칙(URL/메타만·로컬 금지·S3 권장). **(2단계)** notice_repository: upsert_notices_bulk·upsert_notices_bulk_sync 추가(ON CONFLICT DO UPDATE WHERE content_hash IS DISTINCT FROM, RETURNING id). crawl_service: 루프에서 payload 수집 후 일괄 bulk 호출, N+1 제거. **(3단계)** crawler_config: get_crawler(module_name) 레지스트리 API(지연 임포트로 순환 회피). crawl_service: build_notice_payload 순수 함수 추출, get_crawler 사용·importlib 제거, DRY 적용. **(4단계)** app/core/crawl_http.py: fetch_html(Content-Length fail-fast·stream chunking·누적 캡·HtmlTooLargeError). yonsei_glc get_glc_links·scrape_glc_detail에 fetch_html 적용. CI: PostgreSQL 15 서비스 추가·DATABASE_URL 주입·alembic upgrade head·conftest는 DATABASE_URL 없을 때만 빈 문자열.
- [시니어·QA·후임·인프라 피드백 반영] crawl_service·config·문서 — **(유틸·예외·로깅)** `_external_id_from_url`: except 구체화(ValueError, KeyError, AttributeError, IndexError) + 실패 시 logger.warning, **URL 정규화** `_normalize_url_for_hash`(utm/session 등 노이즈 제거 후 해시). `_parse_published_at`: except 구체화 + 실패/미매칭 시 logger.warning(exc_info). **(스레드·OOM)** `asyncio.wait_for(to_thread(...), timeout=30)` 래퍼(get_links·scrape), **MAX_HTML_BYTES**(5MB) 초과 시 해당 공지 스킵. **(설정·가독성)** POLITE_DELAY_SECONDS → `settings.polite_delay_seconds`(config.py·.env POLITE_DELAY_SECONDS), 반환값 `t,d,content` → `title, date_str, html_content`. **(로깅)** crawl_college_sync에서 scrape_fn 호출 try/except, timeout·network vs parser/other 구분 메시지 + exc_info=True. **(문서)** ROADMAP 추가 검토에 Celery→ARQ·레지스트리·httpx·Bulk·CI PostgreSQL·분산 락·Health/마지막 크롤 반영. CAUTIONS "배포 직전 10초 체크리스트" 추가. DEPLOYMENT·.env.example에 POLITE_DELAY_SECONDS 추가.
- [문서] ROADMAP·ADR·검크리스트·Redis 플랜 — (1) **Redis 영속성**: 진행 시 예상 문제에 **Railway Redis 플랜 확인** 추가(무료/저가형 재시작 시 유실 가능, AOF 가능 플랜 확인). DEPLOYMENT Redis 섹션에 동일 문구 반영. (2) **ADR 분리**: `docs/decisions/001-notice-schedule-schema.md` 생성. 일정 스키마 A vs B 결정 근거·비교는 ADR로, ROADMAP에는 결과만(예: "일정 스키마 A 적용") 남기고 전 링크를 ADR로 변경. 작성 규칙에 ADR 분리 원칙 추가. (3) **3단계→4단계 전 검크리스트**: 데이터 품질 검수(실제 약 100건 적재 후 content_hash 중복 없음·날짜 형식 정상) 섹션 추가. 마일스톤에 검크리스트 통과 후 4단계 진입 명시.
- [문서] docs/ROADMAP.md 가독성·구조·모순·사각지대 반영 — (1) **SSOT**: 일정 스키마(A vs B)를 미리 결정 필요 내 "일정 스키마 (A vs B) — 단일 참조" 한 곳에만 상세 기술, 확정 사항·2·3·4·5단계·진행 시 예상 문제에서는 링크만 걸도록 수정. (2) **결정 시점**: "4단계 진입 전" → **"3단계 DB 스키마 확정 전"**으로 변경(3단계 데이터 적재·마이그레이션과 일치). (3) **3단계 중복 축소**: "3단계 진행 과정"의 구현 범위 요약·고려 사항 반영 현황 표 제거, 구현 현황 표 참고 + 미반영·보완 권장만 유지. (4) **Tombstone**: 추가 검토 아이디어에서 Tombstone 항목 삭제(3단계 할 일에만 유지). (5) **사각지대**: raw_html 정제(Clean HTML, Gemini 토큰/400 방지)·크롤링 건별 트랜잭션 분리·Redis 영속성(AOF/RDB) 반영. (6) **4단계**: AI False Positive에 "나와 관련 없는 공지" 피드백→LangSmith/Few-shot 활용 방어적 루프 한 줄 추가. (7) **작성 규칙**: 로드맵 범위(마일스톤·원칙 중심, 세부는 Issues 권장)·단일 참조 원칙 추가. DEPLOYMENT.md Redis 섹션에 영속성(AOF/RDB) 안내 추가.
- [운영·에러·가시성 메타 개선] 계획 반영 — (3단계 당장) crawl_college_sync에서 **placeholder**("제목 없음", "(본문 영역을 찾을 수 없습니다)")를 가비지로 인지해 **continue** 스킵. (3단계 마무리) DEPLOYMENT에 **운영 DB 백업** 섹션 추가(Railway Backups·복구 시나리오). **crawl_runs** 테이블·CrawlRun 모델·006 마이그레이션, crawl_run_repository(create/update_sync, get_recent_crawl_runs), crawl_college_task 진입/종료 시 crawl_run 기록, **GET /internal/crawl-stats** (보안 키 필수). (4단계) worker.py **broker_transport_options = {"visibility_timeout": 3600}**, DEPLOYMENT·CAUTIONS에 visibility_timeout·다중 워커 문구. **process_notice_ai_task** 멱등 처리: get_notice_by_id_sync 추가, **ai_extracted_json** 있으면 스킵.
- [크롤러·트랜잭션·헬스·문서] 계획 반영 — (A) 7개 크롤러 `scrape_*_detail`에서 `except Exception` 후 `return None, ...` 대신 `logger.exception` 후 **raise**로 변경. DOM/셀렉터 변경 시 태스크 실패·Sentry 알림. (B) `crawl_college_sync` 루프 내 `upsert_notice_sync` 성공 후 **건별 `session.commit()`** 추가. 한 건 실패해도 이미 커밋된 건 유지. (4) `/health`에 **DB(SELECT 1)·Redis(PING)** 체크 추가. 응답 `status`(ok/degraded), `db`, `redis` 키. DB 미초기화·Redis 미설정 시에도 200 반환. tests/test_health.py 새 응답 형식에 맞게 수정.
- [문서] ROADMAP·CAUTIONS — (C) IP 차단: "IP 차단(Timeout·403)" 행 추가. Timeout·403 반복 시 IP 차단 의심, 베타 후 **프록시 로테이션**(ScraperAPI, ZenRows) 검토. (D) content_hash: 본문 타겟팅 정교화·**베타 초기 AI 호출·content_hash 업데이트 빈도 모니터링** 문구 추가. Tombstone: 고려 시점 **3단계 마무리** 명시, 추가 검토 아이디어에 Tombstone 항목 추가. CAUTIONS: Timeout·403 시 IP 차단 의심·프록시 검토, content_hash 노이즈·모니터링, Tombstone 부재·3단계 마무리 구현 권장 행 추가.
- [문서] docs/ROADMAP.md — 3단계 진행 과정 명확화 및 고려 사항 반영 현황 정리. "3단계 진행 과정 (코드 기준)" 섹션 추가: 구현 범위 요약, "3단계 고려 사항 반영 현황" 표(진행 시 예상 문제·대비·초석·할 일 상세 전부 점검), 미반영·보완 권장 3건. 특정 기간/소스 재수집·복구 절차 ❌→✅(scripts/delete_notices_for_rerun.py). autoretry_for 비고에 RequestException·retry_backoff_max 반영. 목차에 3단계 구현 현황·진행 과정 링크, 지금 상태에 진행 과정 참고 문구 추가. 서식 통일(표·리스트·구분선 일관성 확인).
- [3단계 크롤러] 의과대·공과대 3건 보완 — yonsei_medicine: 링크에 no 없을 때 기본값 "Post" 부여해 KeyError 방지. yonsei_engineering: Tag|NavigableString → (Tag, NavigableString)으로 Python 3.9 호환, data-file_name 빈 문자열일 때 basename 사용하도록 수정.
- [3단계 크롤러] 크롤러 4건 버그 수정 — yonsei_medicine·yonsei_business: clean_html_content에서 copy.copy 제거, BeautifulSoup(str(element), 'html.parser')로 깊은 복사해 본문 이미지 소실·원본 훼손 방지. yonsei_business: response.encoding을 cp949로 명시(한글 인코딩 오진 방지). yonsei_ai: body_tags를 temp_soup.append(t) 대신 문자열 결합 후 파싱해 DOM 트리 파괴 방지. yonsei_science·yonsei_glc: href 없을 때 urljoin 전 continue 추가해 TypeError 크래시 방지.
- [3단계 크롤러] images JSONB bytes 직렬화 오류 수정 — crawl_college_task 실행 시 `TypeError: Object of type bytes is not JSON serializable` 발생. 원인: base64 인라인 이미지 처리 시 `base64.b64decode(encoded)`로 bytes를 images[].data에 넣어 JSONB 저장 시 psycopg 직렬화 실패. 6개 크롤러(yonsei_engineering, science, business, glc, medicine, underwood)에서 base64 이미지의 `data`를 **디코딩하지 않고** base64 문자열(encoded)만 저장하도록 변경. 불필요한 `import base64` 제거.

## 2026-02-22

- [보안·아키텍처·레이스컨디션 전면 수정] **내부 API**: app/api/internal.py — Query 파라미터 시크릿 완전 제거(Header만: X-Crawl-Trigger-Secret 또는 Authorization: Bearer). college별 Redis 분산락(SET NX EX, TRIGGER_LOCK_TTL 600초)으로 중복 enqueue 방지; app/core/redis.py에 acquire_trigger_lock·release_trigger_lock_sync 추가; crawl_college_task 완료/예외 시 finally에서 락 조기 해제. **Auth**: app/services/auth_service.py — exchange_google_code에 httpx TimeoutException/ConnectError/RemoteProtocolError 캐치 → AuthError("Google auth temporarily unavailable"); google_login에서 sub 클레임 필수 검증(누락 시 AuthError), redirect_uri allowlist(google_redirect_uris) 검사; app/schemas/auth.py TokenPayload·RefreshTokenPayload에 min_length/max_length·extra="forbid"; app/core/config.py에 google_redirect_uris 추가. **main.py**: httpx.HTTPError 전역 핸들러 → 503 Service Unavailable. **헬스체크**: app/api/health.py — app.state 비동기 Redis 클라이언트(Blocklist용) 재사용, await client.ping() + asyncio.wait_for(..., timeout=2). **AI Race Condition**: app/models/notice.py에 ai_status(pending/processing/done); alembic 009_add_notice_ai_status; notice_repository에 get_notice_for_ai_sync(FOR UPDATE SKIP LOCKED)·update_ai_result_sync; process_notice_ai_task는 선점 실패 시 스킵, 스텁에서 update_ai_result_sync로 done 저장; upsert 시 content 변경 분 ai_status='pending' 복원.
- [아키텍처·보안·성능·가독성 완전 개선 구현] **아키텍처**: (1) app/main.py — Sentry 초기화를 환경 변수 로드 직후·파일 최상단으로 이동(lifespan 제거). (2) app/core/database.py — Holder 패턴(_DbHolder·override_db_for_testing)·get_engine/get_async_session_maker 도입, 전역 뮤테이션 제거. (3) ContextVar 기반 transaction() 세션 전파, 중첩 시 동일 세션 재사용, **finally에서 ContextVar.reset(token)·session.close()** 로 커넥션 풀 누수 방지. **보안**: (4) jwt_access_expire_seconds 기본값 3600→600(10분). (5) Access JWT에 jti 발급, Redis Blocklist(app/core/redis.py·create_blocklist_client·add_access_to_blocklist·is_access_blocked) 도입. (6) **Redis 장애 정책**: redis_blocklist_fail_closed(True=Fail-Closed·False=Fail-Open), verify_access_token·is_access_blocked에서 명시적 적용. (7) redis_blocklist_max_connections 명시(Uvicorn 동시 처리량 대응). **확장성**: (8) AsyncKeyFetcher를 lifespan 싱글톤(app.state.google_key_fetcher)·Depends(get_google_key_fetcher)로 주입, auth_service.decode_google_id_token(key_fetcher) 시그니처 변경. **가독성**: (9) POST /v1/auth/logout status_code=204 No Content. (10) tests/test_auth_service.py decode_google_id_token 테스트 key_fetcher 인자로 수정. .env.example에 REDIS_BLOCKLIST_FAIL_CLOSED·REDIS_BLOCKLIST_MAX_CONNECTIONS 추가.
- [코드 리뷰 이슈 전면 반영] **아키텍처**: (1) app/core/database.py — get_db는 세션만 yield(commit/rollback 제거). 서비스 레이어용 transaction() 컨텍스트 매니저 추가, google_login·logout_user가 그 안에서 commit/rollback 제어(옵션 B). (2) verify_db_connection 실패 시 sys.exit(1) 제거, RuntimeError 예외 전파로 변경. (3) app/main.py — Sentry environment 하드코딩 제거, settings.environment 사용. **보안**: (4) app/core/config.py — jwt_secret·google_client_secret·sentry_dsn·crawl_trigger_secret을 SecretStr, jwt_secret·google_client_id·google_client_secret 기본값 제거(Fail-fast). environment 필드 추가. (5) auth_service·main·internal·worker에서 .get_secret_value() 사용, internal 시크릿 비교는 compare_digest 유지. **확장성**: (6) auth_service — 구글 ID 토큰 검증을 pyjwt-key-fetcher(AsyncKeyFetcher) 비동기 JWKS로 전환, asyncio.to_thread 제거. _get_google_key_fetcher 지연 생성(이벤트 루프 필요). **가독성**: (7) app/api/v1/auth.py — HTTPBearer(auto_error=False) 사용, get_current_user_id에서 credentials 의존성으로 Swagger Authorize 동작. (8) app/core/database.py — _async_database_url를 urllib.replace 대신 SQLAlchemy make_url(url).set(drivername="postgresql+asyncpg")로 안전하게 스킴만 교체. requirements.txt에 pyjwt-key-fetcher 추가. tests/conftest.py 필수 env(JWT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET) setdefault. tests/test_auth_service.py — SecretStr 패치·decode_google_id_token 비동기 테스트 및 mock 경로 수정.
- [문서] docs/ROADMAP.md — **시니어 풀스택 엔지니어 리뷰 반영** 섹션 추가. 5가지 관점(아키텍처·코드 품질·성능·보안·유지보수) + 인덱싱·이벤트 루프 블로킹·Heavy 컬럼 지연 로딩을 계획표로 정리. (1) **SRP**: crawl_service에서 url_utils/hash_utils 분리, 흐름 제어만 유지. (2) **코드 품질**: Sentry 데코레이터로 파싱 함수 순수성 유지; **CQ2 P0** 구글 토큰 검증 asyncio.to_thread로 이벤트 루프 블로킹 제거. (3) **성능**: database.py make_url로 안전한 async URL 변환, 청크 후 트랜잭션·expunge 명시; 5단계 목록 API defer(raw_html, images, attachments). (4) **보안**: global_exception_handler에 error_code·message 구조화 응답. (5) **DRY**: notice_repository _build_bulk_upsert_stmt 공통화. (6) **인덱싱**: Notice published_at/created_at B-Tree, hashtags/eligibility GIN, CrawlRun started_at. 목차에 시니어 리뷰 링크 추가.
- [인증 핵심 결함 코드 반영] **Fail 리뷰(총점 40/100)** 4가지 지적을 실제 코드로 수정. (1) **이벤트 루프 블로킹**: auth_service.google_login에서 `decode_google_id_token` 호출을 `await asyncio.to_thread(decode_google_id_token, id_token)`으로 변경. (2) **커넥션 풀 낭비**: main.py lifespan에 `httpx.AsyncClient()` 싱글톤 생성·종료, app/core/deps.py에 get_httpx_client(Request), exchange_google_code에 client 인자·라우터 Depends(get_httpx_client)로 DI. (3) **토큰 생명주기**: User.refresh_token_version 추가(모델·alembic 007), create_jwt_pair(user_id, token_version), verify_access_token·revoke_refresh_tokens_for_user·POST /v1/auth/logout(Authorization Bearer 후 version 증가). (4) **트랜잭션 책임**: get_db에서 yield 후 commit, auth_service에서 session.commit() 제거. ROADMAP에 "인증 핵심 결함 코드 반영" 표·사용자 실행(alembic upgrade head) 안내 추가.
- [크롤링 청킹·인덱스·User 레이스·Defer 구현] **Phase A**: crawl_service — _collect_payloads_sync를 Generator(yield 1건), _collect_payloads_async를 Async Generator로 변경; crawl_college_sync/crawl_college에서 청크 누적·upsert·**잔여 chunk if chunk: 동일 처리**; 예외는 RequestException/httpx.HTTPError·TimeoutException·ValueError·KeyError·AttributeError·TypeError만 catch. get_links 예외 구체화. worker.py Sentry ImportError 시 logger.error 추가. **Phase B**: Notice 모델 published_at/created_at index=True, __table_args__ GIN(hashtags, eligibility); CrawlRun started_at index=True; alembic 008_notice_indexes_and_gin(B-Tree·GIN 수동); user_repository.upsert_by_provider_uid를 insert().on_conflict_do_update().returning(User.id) 단일 쿼리로 재작성; notice_repository에 NOTICE_LIST_DEFER_OPTIONS·목록 조회 defer 원칙 문서화. ROADMAP에 "크롤링 청킹·인덱스·User 레이스·Defer 코드 반영" 표 추가.

## 2026-02-20

- [배포] requirements.txt 배포용 최소화 — Django·Flask·torch·label-studio·langchain·sentence-transformers·Jupyter 등 미사용 패키지 제거. FastAPI·Celery·asyncpg·psycopg-binary·BeautifulSoup·requests·httpx·PyJWT·google-auth·Sentry만 유지. Railway 빌드·이미지 push 시간 단축 목적.
- [3단계 크롤러 이식] 크롤러 파일명 정리 및 Streamlit 제거 — 7개 레포 모듈을 `yonsei_engineering`~`yonsei_business`로 변경·저장, 기존 `yonsei_engineering.py`(클래스형)는 레포 engineering(Streamlit 제거본)으로 교체. Streamlit import·UI 전부 제거해 Celery 워커에서 import 가능한 순수 크롤러만 유지. `app/services/crawlers/`에 7개 yonsei_*.py만 존재.
- [3단계 config·Repository·서비스] crawler_config 모듈명(yonsei_*)·COLLEGE_CODE_TO_MODULE·get_links/scrape_detail 매핑 추가. NoticeRepository.upsert_notice (on_conflict_do_update), CollegeRepository.get_by_external_id 추가. crawl_service: config→get_*_links/scrape_*_detail, 1초 딜레이, external_id(no 우선·URL fallback), content_hash(제목+본문 텍스트 sha256), Repository 호출. tasks.py는 crawl_service.crawl_college 사용하도록 수정. scripts/test_crawler.py 동일.
- [로드맵·문서] 3단계 전 결정 반영 및 6가지 블로커 대비 — ROADMAP: 확정 사항에 "3단계 확정(구현 원칙)"(payload는 notice_id만, content_hash 노이즈 제거, upsert on_conflict_do_update·Repository, Celery 워커 psycopg2, Redis rediss 지원, Polite crawling 1초·순차, 크롤 주기 1시간, external_id no/URL). 미리 결정 필요 3단계 항목 결정 완료로 정리. 진행 시 예상 문제에 Celery payload·Redis TLS·방화벽 행 추가. 3단계·4단계 할 일 보강. CAUTIONS: 크롤러·AI 섹션에 payload·content_hash·Polite·Redis TLS·Upsert·AI notice_id만 행 추가. DEPLOYMENT: Redis rediss·SSL 옵션 안내.
- [ROADMAP 3단계 구현 현황] 레포 이식·upsert·content_hash·DB 접근 repositories만 반영 — SeaLion-hub/crawler 기준·사이트별 모듈 분리·config·upsert·content_hash 저장·아키텍처 규칙 행을 완료(✅)로 갱신.
- [3단계 초석] content_hash 변경 시 4단계 AI 큐 enqueue·로깅·재수집·문서 — NoticeRepository `get_by_college_external_sync` 추가. crawl_college_sync 반환 (count, notice_ids), upsert 전 기존 해시 비교 후 변경·신규만 process_notice_ai_task.delay(notice_id). tasks: process_notice_ai_task 스텁(rate_limit 10/m), task_id·college_code 로그·Sentry 태그. ROADMAP "3단계에서 더 신경 쓸 부분(초석)" 섹션·구현 현황 content_hash 행 갱신. scripts/delete_notices_for_rerun.py 추가. DEPLOYMENT trigger-crawl 헤더 X-Crawl-Trigger-Secret·재수집 절차. README Crawler 문구 수정.
- [의대 크롤러] `yonsei_medicine.py` get_medicine_notice_links — 모든 항목에 `"no": "Post"`를 넣어 12건이 한 행으로만 upsert되던 문제 수정. URL 쿼리에서 articleNo/article_no/no/id 추출해 항목별 고유 `no` 부여, 없으면 `no` 생략해 crawl_service의 _external_id_from_url fallback 사용. scrape_detail·반환 구조·문서 규칙 유지.

---

## 2026-02-18

- [문서] docs/ROADMAP.md — 확정 사항 "일정 저장"을 4단계 진입 전 결정 필요로 변경, "일정 스키마 (4·5·6 공통)" 행 추가(A/B 선택지). 2·4·5단계 문구를 "결정된 스키마" 전제로 수정해 005 스키마(dates/eligibility)와 구 컬럼(deadline/event_*) 모순 제거. 추가 검토 아이디어에 수정 기록.
- [문서] docs/ROADMAP.md — 지금 상태를 "3단계 진행 중"으로 갱신, 3단계 구현 현황 표(할 일별 ✅/❌)·할 일 상세·검증·마일스톤 보강. 미리 결정 필요에 Notice 일정 스키마 정합성(4단계 진입 전) 추가. WORK_LOG 작성 규칙에 맞게 본일자 3단계 항목 재정리.
- [3단계] app/core/crawler_config.py — 사이트별 URL·selectors(row, link) config 분리. 하드코딩 방지, CAUTIONS 준수.
- [3단계] app/services/crawlers/yonsei_engineering.py — 공대 게시판 크롤러(httpx+BeautifulSoup). 제목·본문·이미지(URL+Base64)·첨부파일 수집, (college_id, external_id) 중복 시 스킵. 표 HTML 유지·라벨 기반 본문 추출.
- [문서] docs/ROADMAP.md, docs/CAUTIONS.md — 블로커·병목 검증 후 반영: 일정 스키마 성능 근거(DateTime vs JSONB), content_hash 생성 기준(미리 결정 필요), 진행 시 예상 문제·대비 표(Celery DB 풀·429 백오프·Playwright OOM·False Positive), 추가 검토에 AI False Positive 보완. CAUTIONS에 Celery+비동기 DB 풀·Playwright 최후 수단 문구 추가.
- [3단계] app/services/tasks.py — Celery 태스크 crawl_college_task(college_code), asyncio.run(run_crawler_async). integrations.mdc(동기 def+asyncio.run) 준수.
- [3단계] app/core/config.py — redis_url(또는 REDIS_URL) 등 환경변수. .env.example에 REDIS_URL·CRAWL_TRIGGER_SECRET 반영됨.
- [2단계·스키마] app/models/notice.py — published_at, images, attachments, dates, eligibility(JSONB) 추가. alembic 534657f22f86(published_at), 005_refactor_schema(deadline/event_*/poster_image_url 제거, dates·eligibility·images·attachments 추가). 4·5단계 일정 API와 스키마 정합성은 ROADMAP 미리 결정 필요에 기록.
- [2단계·시드] scripts/seed_colleges.py — 단과대 기초 데이터(공과대학 등) 시딩.
- [검증] scripts/test_crawler.py — 공대 게시판 수집·DB 저장 테스트. (Celery 앱·worker.py 진입점, POST /internal/trigger-crawl, Dockerfile, Sentry 워커, upsert·content_hash·Repository 분리는 미구현 — ROADMAP 3단계 구현 현황 표에 반영.)
- [문서] ROADMAP 점검 반영·가독성 정리 — 3단계 구현 현황에 "Celery 워커 DB (동기 psycopg2)" 행 추가(❌). 1단계 Railway 문구에 Celery 앱 진입점·워커 구성 후 Nixpacks 가능 명시. 4단계 DB 저장을 (A)/(B) 선택지별로 구분해 기술. 미리 결정 필요 3단계 College에 시드·config 갱신 보강. 3단계 구현 현황 안내 문장·Notice 일정 스키마 문단 정리. README "현재"를 3단계 진행 중으로 통일.

---

## 2026-02-16

- [Cursor 규칙] .cursor/rules/user-actions.mdc 추가 — 사용자가 직접 설정·실행할 부분은 항상 명시하고, 진행 전 사용자 확인 요청. CAUTIONS에 user-actions 안내 추가.
- [로드맵] 일정·달력 핵심 기능 구체 반영 — 2단계 Notice·user_calendar_events 설계, 4단계 추출 스키마에 일정 필드, 5단계 일정 API·.ics·구글 캘린더 내보내기, 6단계 서비스 내부 달력 UI·내보내기 UI.
- [Cursor 규칙] .cursor/rules/ 에 tech-stack.mdc, architecture.mdc, integrations.mdc 추가·보완. SQLAlchemy 2.0·Pydantic v2·Depends·async 블로킹 금지 / 계층 분리·호출 방향 / Gemini·Celery rate_limit·Playwright. docs/CAUTIONS.md 에 Cursor 규칙 안내 문장 추가.
- [로드맵·문서] Sentry 1단계, OAuth 핸드쉐이크 2단계, Playwright OOM(옵션·concurrency) 3단계 반영. docs/CAUTIONS.md 추가 — 바이브 코딩 시 주의사항·체크리스트 전부 정리. ROADMAP·DEPLOYMENT·README 링크 반영.
- [로드맵·문서] Auth 구글 우선으로 변경. ROADMAP·DEPLOYMENT·README 전면 반영 — 검증/롤백/환경/시크릿/에러/upsert/데이터흐름/4·5 스키마 공유/Sentry 3단계/의존성/API 버전/진입점/비용 등 비판 반영.
- [문서] README, ROADMAP, DEPLOYMENT, WORK_LOG 가독성 개선 — 소제목·테이블·문단 나누기, 중복 정리.
- [문서] README.md 정리 — 아이디어(문제/목표), MVP(SeaLion-hub/DICE test) 참조, 이 레포 재구축 맥락, docs 링크, 로컬 실행 예정.
- [로드맵] docs/ROADMAP.md 전면 수정 — Playwright Railway Dockerfile, Auth(OAuth+JWT) 2단계 반영, Celery AI 태스크 rate_limit 명시. 인프라·인증·429 대응 누락 보완.
- [배포] docs/DEPLOYMENT.md 추가 — Railway(백엔드)·Vercel(프론트) 기준 설정 정리. .cursor/rules에 배포 환경 기본 가정 및 "프론트 폴더는 6단계에서 생성" 명시.

---

## 2026-02-17

- [로드맵·비판 반영] 4가지 검토 사항 반영 — (1) 3단계: API 역공학 사전 조사(httpx 우선), 크롤러 설정(선택자·URL) config 분리. (2) 4단계: AI False Positive 지향(애매하면 노출) 프롬프트 규칙, 429 지수 백오프. CAUTIONS·integrations.mdc 동기화.
- [로드맵·결정 사항] 3·4·5단계 반드시 정할 항목 반영 — ROADMAP.md: 공지 유니크 (college_id, external_id), 스케줄러 Railway Cron + /internal/trigger-crawl, 4단계 입출력·자격요건 스키마·rate_limit 10/m, 5단계 user_calendar UniqueConstraint·일정 API year/month 스펙. DEPLOYMENT.md Cron 섹션 및 CRAWL_TRIGGER_SECRET, .env.example REDIS_URL·CRAWL_TRIGGER_SECRET 추가.
- [2단계 모델] Notice에 hashtags(JSONB) 컬럼 추가. UserCalendarEvent에 UniqueConstraint(user_id, notice_id) 추가. alembic/versions/004_add_hashtags_and_user_calendar_unique.py 마이그레이션 생성.
- [1단계] requirements.txt, requirements-dev.txt 생성. fastapi, uvicorn, sqlalchemy, alembic, asyncpg, pydantic-settings, sentry-sdk 버전 고정.
- [1단계] app/ 패키지 및 계층형 디렉터리 구조 생성 (api/, core/, services/, repositories/, models/, schemas/).
- [1단계] app/main.py — FastAPI 앱, /health 라우터, 전역 예외 핸들러, Sentry 초기화(lifespan).
- [1단계] app/api/health.py — GET /health → 200 + {"status":"ok"}.
- [1단계] app/core/config.py — pydantic-settings로 SENTRY_DSN, DATABASE_URL 환경변수 로드.
- [1단계] .env.example, .gitignore 생성. DEPLOYMENT.md에 SENTRY_DSN 환경변수 추가.
- [1단계] 로컬 검증 완료: uvicorn app.main:app 실행 후 GET /health → {"status":"ok"}. Railway 배포는 사용자 진행 예정.
- [1단계] Railway 배포 및 마일스톤 달성: Railway 도메인에서 GET /health → 200 + {"status":"ok"} 확인 완료. 1단계 완료.
- [2단계] app/core/database.py — 비동기 엔진, get_db, init_db, verify_db_connection. CAUTIONS 준수: 연결 실패 시 Sentry 보고 후 sys.exit(1).
- [2단계] app/main.py — lifespan에 init_db·verify_db_connection, CORS 미들웨어 추가.
- [2단계] app/models/ — Base, College, Notice, User, UserCalendarEvent. SQLAlchemy 2.0 Mapped·mapped_column. (college_id, external_id), (provider, provider_user_id) 유니크.
- [2단계] app/schemas/ — UserBase, UserCreate, UserResponse, UserProfile, TokenPayload, TokenResponse, RefreshTokenPayload.
- [2단계] alembic 초기화, env.py 비동기 설정, versions/001_initial.py 수동 생성.
- [2단계] app/repositories/user_repository.py — get_by_provider_uid, upsert_by_provider_uid.
- [2단계] app/services/auth_service.py — exchange_google_code, decode_google_id_token, create_jwt_pair, google_login.
- [2단계] app/api/v1/auth.py — POST /v1/auth/google. config·.env.example에 JWT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ALLOWED_ORIGINS 추가.
- [2단계] docs/DEPLOYMENT.md — OAuth 핸드쉐이크(응답 body JSON) 확정 및 문서화.
- [2단계] requirements.txt — pyjwt, httpx 추가. 2단계 마일스톤 달성.
- [2단계] README.md — 로컬 실행 안내(uvicorn, alembic upgrade head), /health·/v1/auth/google 엔드포인트 설명.
- [2단계·디버그] Alembic 마이그레이션 UnicodeDecodeError·연결 실패 원인 규명 — psycopg2가 오류를 마스킹함. psycopg3 전환, creator로 포트 확실 적용. 실제 원인: 시스템 DATABASE_URL이 .env를 덮어씀. env.py psycopg3+creator, DEPLOYMENT에 DATABASE_URL 우선순위·DB 생성 안내 추가.
- [2단계·정리] Railway DB(DATABASE_PUBLIC_URL)로 마이그레이션 성공. alembic/env.py 디버그 로그 제거.
- [2단계·로컬 실행] ModuleNotFoundError(httpx, pyjwt) — pip install -r requirements.txt. Windows+asyncpg/psycopg 이슈 — run.py 추가(이벤트 루프 정책 선설정), database.py에서 postgresql+psycopg 사용. README 갱신.
- [2단계·배포] nixpacks.toml 추가 — 배포 시 `alembic upgrade head` 자동 실행 후 uvicorn 시작. DEPLOYMENT.md 빌드 설정에 반영.
- [2단계·배포] requirements.txt에 greenlet 추가 — Railway에서 "No module named 'greenlet'" 원인. SQLAlchemy AsyncSession에 greenlet 필수.
- [2단계·설정] JWT 만료 시간 환경변수화 — config.py에 jwt_access_expire_seconds, jwt_refresh_expire_days 추가. auth_service.py 하드코딩 제거. .env.example·DEPLOYMENT 갱신.
- [2단계·설정] DB 연결 검증 재시도 — verify_db_connection()에 retry 로직 추가. db_connect_retries(기본 5), db_connect_retry_interval_sec(기본 2) 설정 가능. Railway 컨테이너 환경 대비.
- [2단계·정리] DB·예외·패키지 4가지 수정 — (1) database.py _to_async_url 제거, asyncpg 직접 사용. run.py 이벤트 루프 정책으로 Windows 이슈 해결. (2) alembic/versions/002_fix_timestamp_nullable.py 추가, created_at·updated_at nullable=False. (3) main.py RequestValidationError 핸들러 추가, 422 마스킹 해결. (4) requirements.txt psycopg2-binary 제거.
- [로드맵·스키마] 4가지 개선점 반영 — (1) content_hash·is_manual_edited Notice 모델·003 마이그레이션 추가. (2) ROADMAP 2단계 본문 해시·수동 수정 플래그 설계, 3단계 content_hash 기반 변경 감지, 4단계 해시 변화 시에만 AI 재추출·is_manual_edited 덮어쓰기 방지, 5단계 FTS·GIN 인덱스, 추가 검토 API Rate Limit(slowapi).
- [보안·인프라] main.py — lifespan에 engine.dispose() 추가(커넥션 풀 종료), Exception 핸들러에서 asyncio.CancelledError 필터(re-raise로 정상 연결 종료 시 500 로그 방지).
- [로드맵] 보안·Auth 3건 반영 — 2단계 구글 ID 토큰 서명 검증(베타 전 google-auth), 추가 검토 토큰 무효화·로그아웃(Redis 블랙리스트·token_version), 5단계 GET /v1/users/me(프로필 매칭·설정 UI 필수).
- [테스트·CI] pytest·mypy·Ruff·GitHub Actions 도입 — requirements-dev에 mypy·pytest-asyncio, pyproject.toml(pytest·ruff·mypy 설정), tests/conftest·test_health, .github/workflows/ci.yml. Push/PR 시 Ruff→Mypy→Pytest 자동 실행. 1단계 검증(변동 대비) 완료.
- [기술 부채 Phase A] 3단계 전 수정 — (1) get_db 오토 커밋 제거, google_login에 session.commit() 명시. (2) google-auth verify_oauth2_token으로 ID 토큰 서명 검증 적용. (3) tests/test_auth_service.py 추가(create_jwt_pair·decode_google_id_token 단위 테스트). ROADMAP Phase B(Repository DTO·테스트 확장·Observability) 추가 검토에 기록.
- [배포 수정] requirements.txt에 requests 추가 — google-auth의 `transport.requests`가 JWKS fetch 시 requests 패키지 필요. Railway 배포 시 ModuleNotFoundError 해결.
- [로드맵·모바일] 6단계에 반응형·모바일 우선·터치 친화적 UI·목록·이미지 로딩 전략·스켈레톤·네트워크 에러 안내·프로필 폼 모바일 대응·스크롤 복원 반영. 추가 검토에 PWA·웹 푸시·OG 태그·Web Share API·데이터 절약 모드·접근성(WCAG)·OAuth 모바일 플로우 검증 반영.
- [로드맵] docs/ROADMAP.md — 확정 사항(코드·문서 기준) 섹션·단계별 목표 기간 표 추가. 2단계 Raw/일정/OAuth 문구를 "확정" 표현으로 정리. 6단계 달력 UX 확정(한 화면 통합+시각적 구분+토글 필터, 탭 비권장) 반영. 추가 검토 아이디어에 단계별 기간 표 링크 보강.
- [로드맵·문서] ROADMAP에 "미리 결정 필요 (진입 전)" 섹션 추가. 3·4·5단계별 결정 권고 항목 표로 정리. CAUTIONS 중복 수집 문구를 확정 사항(URL 미사용)과 맞춤. 추가 검토 아이디어에 문서 정합성 점검 항목 추가.
- [문서] README.md 개선 — 현재 상태 한 줄, 기술 스택 표, 로컬 실행 전제(Python 3.10+, PostgreSQL, .env.example), 문서 표에 ROADMAP 확정 사항 안내, Swagger /docs 안내, 참고 섹션 정리.

---

## 템플릿 (새 날짜에 복사)

```markdown
## YYYY-MM-DD

- [단계] 무엇을 했는지 (어떤 파일/기능). 왜 또는 결과 한 줄.
```