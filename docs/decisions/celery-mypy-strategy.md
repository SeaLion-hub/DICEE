# Celery + Mypy 전략

## 상태

- **런타임**: `app/services/tasks.py`에서 Celery 5.x `@app.task`로 동기 태스크 정의.
- **Mypy**: `pyproject.toml`에서 `celery` / `celery.*`에 `ignore_missing_imports = true` 유지 (서드파티 스텁 미완·데코레이터로 시그니처 흐림 대비).
- **개발 의존성**: `requirements-dev.txt`에 **`celery-types`** 포함. IDE·향후 `ignore_missing_imports` 완화 시 참조.

## 선택한 방향 (단일 전략)

1. **스텁**: [celery-types](https://pypi.org/project/celery-types/)를 dev에만 설치. `Task.apply_async` 시그니처가 좁은 `Protocol`과 어긋날 수 있어, [`app/adapters/celery_crawl_dispatcher.py`](../../app/adapters/celery_crawl_dispatcher.py) 태스크 할당 한 줄은 `# type: ignore[assignment]` 유지.
2. **태스크 모듈**: `app.services.tasks`는 **`disallow_untyped_defs` 오버라이드 대상에서 제외** (명시적 모듈 리스트로만 엄격화). `@shared_task` / `@app.task`가 붙은 **최상위 함수**는 mypy `misc`(untyped decorator)가 나오기 쉬움.
3. **경계 타입**: 디스패처·헬퍼는 **`Protocol` + `cast`** 또는 이미 타입이 잡힌 래퍼로 유지 ([`app/adapters/celery_crawl_dispatcher.py`](../../app/adapters/celery_crawl_dispatcher.py) 패턴).
4. **점진적 강화**: 태스크 **본문 내부**의 순수 함수·헬퍼는 다른 `app.services.*` 모듈로 옮기면 해당 모듈에 `disallow_untyped_defs` 적용 가능.

## 하지 않는 것

- 전역 `mypy --strict`와 동시에 `tasks.py` 전체를 한 번에 고치기.
- 태스크마다 무분별한 `# type: ignore`.

## 품질 게이트

- `mypy app`, `ruff check app tests`, `pytest tests` CI 통과 유지.
