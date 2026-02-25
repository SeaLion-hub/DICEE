from pathlib import Path

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
    monkeypatch.setattr(storage, "settings", storage.settings.model_copy(update={"s3_content_prefix": ""}))
    college_id = "11111111-1111-1111-1111-111111111111"
    external_id = "../weird/id\\with\\separators"
    key = storage._object_key(college_id, external_id, content_hash=None)
    # 전체 키 문자열은 경로 구분자를 포함할 수 있지만, 파일명 부분은 sanitize 되어야 한다
    filename = key.split("/")[-1]
    for ch in filename:
        assert ch.isalnum() or ch in {".", "_", "-"}


def test_upload_local_does_not_escape_base(tmp_path, monkeypatch):
    # content_storage_local_path를 임시 디렉터리로 고정
    monkeypatch.setattr(
        storage,
        "settings",
        storage.settings.model_copy(
            update={
                "content_storage_local_path": str(tmp_path),
                "content_upload_failure_policy": "allow_none",
            }
        ),
    )

    # 정상적인 키는 base 아래에만 저장된다
    key = "subdir/test.html"
    url = storage._upload_local("<html>ok</html>", key)
    expected_path = (Path(tmp_path) / key).resolve()
    assert expected_path.exists()
    assert url.endswith("/" + key)

    # base 밖으로 나가려는 키는 무시된다
    escaped_key = "../escape.html"
    url2 = storage._upload_local("<html>bad</html>", escaped_key)
    assert url2 is None
    # 실제 파일이 생성되지 않았는지 확인
    assert not (Path(tmp_path).parent / "escape.html").exists()

