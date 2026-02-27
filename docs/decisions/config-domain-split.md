# ADR: Config 도메인별 분리 및 구형 접근 하드 리밋

**상태**: 채택  
**배경**: `Settings` 단일 클래스에 DB, Redis, JWT, S3, 크롤, 레이트 리밋 등 50개 이상 필드가 혼재하여 God Object가 됨. 도메인별 설정 분리 및 마이그레이션 기한·하드 리밋 정책 수립.

---

## 결정

1. **도메인별 설정 그룹**: `DatabaseConfig`, `RedisConfig`, `JwtConfig`, `AuthGoogleConfig`, `CrawlerConfig`, `StorageConfig`, `RateLimitConfig` 등으로 논리적 그룹을 나눈다. `Settings`는 이들을 `settings.db`, `settings.redis`, `settings.jwt` 등으로 노출한다.
2. **마이그레이션 기한**: 구형 평탄화 필드(`settings.database_url` 등) 사용을 **1 스프린트** 내에 `settings.db.database_url` 등 신규 경로로 이전한다. 기한은 팀 롤아웃 계획에 따라 고정한다.
3. **하드 리밋 (기한 이후)**: 구형 접근 방식 사용 시 DeprecationWarning이 아니다. **앱이 기동되지 않도록(Fail at boot)** 한다. 즉, `LEGACY_CONFIG_FORBIDDEN=true`(또는 동일 의미의 환경 변수) 설정 시 구형 property 접근 시 `RuntimeError`를 발생시켜 프로세스가 종료되도록 한다. 기한 이후에는 모든 호출부가 `settings.db.*`, `settings.redis.*` 등만 사용해야 한다.
4. **구현 순서**: 먼저 `settings.db`, `settings.redis` 등 뷰를 추가하고, 호출부를 점진적으로 이전한 뒤, 마이그레이션 기한 후 구형 접근 시 예외를 발생시키는 메커니즘을 활성화한다.

---

## 참고

- [app/core/config.py](../../app/core/config.py): `Settings`, 도메인 뷰(`.db`, `.redis` 등). 구형 평탄 필드 접근 차단은 `Settings.__getattribute__` 가드(구형 필드명 집합)로 구현되어 있으며, `LEGACY_CONFIG_FORBIDDEN=true` 시 해당 필드 접근 시 `RuntimeError` 발생.
- 마이그레이션 기한 및 `LEGACY_CONFIG_FORBIDDEN` 정책은 배포·CI에서 적용.
