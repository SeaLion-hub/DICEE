from pathlib import Path
from uuid import UUID

import app.core.config as app_config
import app.core.storage._spool_ops as storage_spool_ops
from app.core import storage


def test_sanitize_external_id_basic_characters():
    assert storage._sanitize_external_id_for_key("abc-123_.") == "abc-123_."


def test_sanitize_external_id_disallowed_characters_replaced():
    value = "a/b\\c ../.. ..\\secret 한글🚀"
    sanitized = storage._sanitize_external_id_for_key(value, fallback_seed="seed")
    # 허용 문자만 남아 있는지 확인
    for ch in sanitized:
        assert ch.isalnum() or ch in {".", "_", "-"}
    # 디렉터리 조작에 사용되는 패턴은 제거되어야 한다
    assert ".." not in sanitized


def test_sanitize_external_id_empty_uses_unknown_with_hash():
    sanitized = storage._sanitize_external_id_for_key("", fallback_seed="seed")
    assert sanitized.startswith("unknown")
    assert len(sanitized) > len("unknown")


def test_object_key_uses_sanitized_external_id(monkeypatch):
    # s3_content_prefix가 비어 있을 때 college_id/… 형태로 생성되는지 확인
    monkeypatch.setattr(
        app_config,
        "settings",
        app_config.settings.model_copy(update={"s3_content_prefix": ""}),
    )
    college_id = UUID("11111111-1111-1111-1111-111111111111")
    external_id = "../weird/id\\with\\separators"
    key = storage._object_key(college_id, external_id, content_hash=None)
    # 전체 키 문자열은 경로 구분자를 포함할 수 있지만, 파일명 부분은 sanitize 되어야 한다
    filename = key.split("/")[-1]
    for ch in filename:
        assert ch.isalnum() or ch in {".", "_", "-"}


def test_upload_local_does_not_escape_base(tmp_path, monkeypatch):
    # content_storage_local_path를 임시 디렉터리로 고정
    monkeypatch.setattr(
        app_config,
        "settings",
        app_config.settings.model_copy(
            update={
                "content_storage_local_path": str(tmp_path),
                "content_upload_failure_policy": "allow_none",
            }
        ),
    )

    # 정상적인 키는 base 아래에만 저장된다
    key = "subdir/test.html"
    url = storage._upload_local("<html>ok</html>", key)
    assert url is not None
    expected_path = (Path(tmp_path) / key).resolve()
    assert expected_path.exists()
    assert url.endswith("/" + key)

    # base 밖으로 나가려는 키는 무시된다
    escaped_key = "../escape.html"
    url2 = storage._upload_local("<html>bad</html>", escaped_key)
    assert url2 is None
    # 실제 파일이 생성되지 않았는지 확인
    assert not (Path(tmp_path).parent / "escape.html").exists()


def test_apply_error_metadata_adds_expected_fields():
    entry = {"college_id": "c", "external_id": "e", "html_content": "h"}
    updated = storage.apply_error_metadata(
        entry,
        error=RuntimeError("x" * 1000),
        stage="upload",
        retry_count=3,
    )
    assert updated[storage.SPOOL_RETRY_COUNT_KEY] == 3
    assert updated[storage.SPOOL_LAST_ERROR_TYPE_KEY] == "RuntimeError"
    assert len(updated[storage.SPOOL_LAST_ERROR_MESSAGE_KEY]) == storage.SPOOL_LAST_ERROR_MESSAGE_MAX_LEN
    assert updated[storage.SPOOL_LAST_ERROR_STAGE_KEY] == "upload"
    assert storage.SPOOL_LAST_ERROR_AT_KEY in updated


def test_spool_read_entry_accepts_legacy_payload(tmp_path):
    file_path = tmp_path / "legacy.json"
    file_path.write_text(
        '{"college_id":"a","external_id":"b","html_content":"<html></html>","retry_count":1}',
        encoding="utf-8",
    )
    entry = storage.spool_read_entry(file_path)
    assert entry is not None
    assert entry["college_id"] == "a"


def test_spool_move_to_dlq_s3_writes_dead_letter_metadata(monkeypatch):
    puts = []
    deletes = []

    class _FakeClient:
        def put_object(self, **kwargs):
            puts.append(kwargs)

        def delete_object(self, **kwargs):
            deletes.append(kwargs)

    monkeypatch.setattr(
        app_config,
        "settings",
        app_config.settings.model_copy(update={"s3_bucket": "bucket", "content_spool_s3_prefix": "pref"}),
    )
    monkeypatch.setattr(storage_spool_ops, "_build_s3_client", lambda: _FakeClient())

    moved = storage.spool_move_to_dlq_s3(
        "pref/123.json",
        {"college_id": "a", "external_id": "b", "html_content": "h"},
        reason="max_retries_exceeded",
    )
    assert moved is True
    assert len(puts) == 1
    assert len(deletes) == 1
    body = puts[0]["Body"].decode("utf-8")
    assert "dead_lettered_at" in body
    assert "max_retries_exceeded" in body


def test_spool_list_s3_skips_dlq_entries(monkeypatch):
    class _FakePaginator:
        def paginate(self, **kwargs):
            return [
                {
                    "Contents": [
                        {"Key": "pref/1.json"},
                        {"Key": "pref/dlq/2.json"},
                        {"Key": "pref/3.txt"},
                    ]
                }
            ]

    class _FakeClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return _FakePaginator()

    monkeypatch.setattr(
        app_config,
        "settings",
        app_config.settings.model_copy(update={"s3_bucket": "bucket", "content_spool_s3_prefix": "pref"}),
    )
    monkeypatch.setattr(storage_spool_ops, "_build_s3_client", lambda: _FakeClient())

    keys = storage.spool_list_s3()
    assert keys == ["pref/1.json"]
