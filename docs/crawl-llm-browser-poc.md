# LLM 브라우저 크롤 (Stagehand 유사) PoC 범위

Crawlee v3.16의 StagehandCrawler처럼 **자연어·시각 기반 브라우저 제어**는 비용·지연·불확실성이 크다. DICEE 기본 경로는 **정적 HTML + 필요 시 Playwright + 기존 AI 파이프라인**을 유지한다.

## PoC를 할 때만 지킬 조건

1. **격리:** 별도 Celery 큐(예: `crawl_llm`) 또는 별도 워커 서비스·`concurrency=1`. 기본 `crawl` 큐와 코드 경로 분리.
2. **기능 플래그:** 프로덕션 기본값 `off`. 예: 환경 변수 `LLM_BROWSER_CRAWL_ENABLED=false`.
3. **비용 상한:** 호출당·일당 RPM/토큰 예산을 Railway Variables로 고정하고 초과 시 폴백.
4. **폴백:** LLM 단계 실패 시 기존 `scrape_detail` 또는 수동 백필로 끝낸다.
5. **관측:** `college_code`, 시도 ID, 모델명을 구조화 로그·메트릭에 남긴다.

## 현재 저장소 상태

PoC 구현체는 **본 문서로 범위만 고정**한다. 구현 시 ADR·WORK_LOG에 착수·결과를 남긴다.
