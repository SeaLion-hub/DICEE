# ADR: 본문 업로드 실패 스풀 및 드레인

## 상태

수락 (2025-02)

## 배경

`content_upload_failure_policy=fail` 시 S3/로컬 업로드 실패는 예외로 전파되어 크롤이 중단된다. 유실을 0에 수렴시키려면 실패 건을 기록했다가 재처리해야 하며, 재처리 시 **재업로드만 하면 고아 객체**가 되므로 **DB(notice_contents) 반영**까지 포함해야 한다.

## 결정

- **스풀 기록**: policy=fail인 경우 업로드 예외 발생 전에 페이로드(college_id, external_id, content_hash, html_content, retry_count)를 스풀에 동기 기록 후 예외 전파.
- **스풀 저장소**: 로컬 기본 경로는 컨테이너 재배포 시 유실 가능. 프로덕션에서는 **영속 볼륨** 또는 **외부 큐(S3/SQS)** 사용. `content_spool_backend`(local | s3) 등으로 선택.
- **드레인**: Beat 주기 태스크 `drain_content_spool_task`가 (1) 스풀에서 읽기 → (2) `upload_notice_html` 재호출 → (3) **`update_notice_content_url_sync`로 notice_contents upsert** 후 스풀에서 제거. 실패 시 retry_count 증가, 최대 재시도 후 DLQ 디렉터리로 이동.
- Repository에 `update_notice_content_url_sync(session, college_id, external_id, content_url)` 추가.

## 결과

- 크롤 시 업로드 실패 시에도 스풀에 남고, 드레인이 재업로드 및 DB 반영까지 수행해 정합성 유지.
- CONTENT_SPOOL_DIR·CONTENT_SPOOL_BACKEND·CONTENT_SPOOL_MAX_RETRIES 설정 및 배포 가이드 반영.
