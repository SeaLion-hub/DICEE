"""공지 본문 스토리지. S3 또는 로컬에 저장 후 content_url 반환."""

import hashlib
import logging
import re
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.metrics import CONTENT_UPLOAD_FAILURE_TOTAL, increment

logger = logging.getLogger(__name__)


def upload_notice_html(
    html_content: str | None,
    *,
    college_id: uuid.UUID,
    external_id: str,
    content_hash: str | None = None,
) -> str | None:
    """
    공지 본문 HTML을 스토리지에 저장하고 접근 URL을 반환.
    html_content가 None이거나 비면 None 반환.
    """
    if not (html_content or "").strip():
        return None
    key = _object_key(college_id, external_id, content_hash)
    if (settings.content_storage_type or "").lower() == "s3" and settings.s3_bucket:
        return _upload_s3(html_content, key)
    return _upload_local(html_content, key)


def _sanitize_external_id_for_key(external_id: str, *, fallback_seed: str | None = None) -> str:
    """
    스토리지 키용 external_id 정규화.
    - 허용 문자: A-Z, a-z, 0-9, '.', '_', '-'
    - 그 외 문자는 '_' 로 치환.
    - '..', '../', '..\\' 등의 경로 조작 패턴을 무력화.
    - 결과가 비거나 과도하게 길면 해시를 섞어 충돌을 줄인다.
    """
    raw = (external_id or "").strip()
    if not raw:
        if fallback_seed:
            digest = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:8]
            return f"unknown_{digest}"
        return "unknown"

    # 일단 허용 문자만 남기고 나머지는 '_' 로 치환
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)

    # '..', '../', '..\\' 등은 더 이상 디렉터리 구분자로 쓰이지 않지만,
    # 파일명에 그대로 남겨둘 필요는 없으므로 한 번 더 정리
    while ".." in safe:
        safe = safe.replace("..", "_")

    # 연속된 구분자로 인해 '_' 가 길게 이어지는 경우 정규화
    safe = re.sub(r"_+", "_", safe).strip("_")

    if not safe:
        if fallback_seed:
            digest = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:8]
            return f"unknown_{digest}"
        return "unknown"

    # 너무 길면 앞부분과 해시를 조합해 길이를 제한
    max_len = 150
    if len(safe) > max_len:
        digest_source = safe
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:8]
        prefix = safe[: max_len - 1 - len(digest)]
        safe = f"{prefix}_{digest}"

    return safe


def _object_key(college_id: uuid.UUID, external_id: str, content_hash: str | None) -> str:
    """스토리지 객체 키. 동일 college+external_id면 덮어쓰기."""
    ext_for_hash = external_id or ""
    h = (content_hash or hashlib.sha256((str(college_id) + ext_for_hash).encode()).hexdigest())[:16]
    safe_ext = _sanitize_external_id_for_key(ext_for_hash, fallback_seed=f"{college_id}_{h}")
    prefix = (settings.s3_content_prefix or "").strip().strip("/")
    if prefix:
        return f"{prefix}/{college_id}/{h}_{safe_ext}.html"
    return f"{college_id}/{h}_{safe_ext}.html"


def _upload_s3(html_content: str, key: str) -> str | None:
    """S3에 업로드 후 URL 반환. boto3 선택 의존."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        logger.warning("boto3 not installed; cannot upload to S3. Install boto3 or use content_storage_type=local.")
        return None
    bucket = settings.s3_bucket
    if not bucket:
        return None
    try:
        client = boto3.client("s3", region_name=settings.s3_region)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=html_content.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
        )
        return f"https://{bucket}.s3.{settings.s3_region}.amazonaws.com/{key}"
    except ClientError as e:
        logger.exception("S3 upload failed: key=%s error=%s", key, e)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        if (settings.content_upload_failure_policy or "").strip().lower() == "fail":
            raise
        return None


def _upload_local(html_content: str, key: str) -> str:
    """로컬 디렉터리에 저장 후 base_url 또는 상대 경로 반환. file:// 절대 경로는 노출하지 않음."""
    base = Path(settings.content_storage_local_path or "storage/contents").resolve()
    path = (base / key).resolve()

    try:
        # base 디렉터리 밖으로 이탈하는 경로는 거부
        path.relative_to(base)
    except ValueError:
        logger.error("Local content path escaped base: base=%s key=%s path=%s", base, key, path)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        policy = (settings.content_upload_failure_policy or "").strip().lower()
        if policy == "fail":
            raise ValueError("Invalid content key; escaped storage base directory")
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_content, encoding="utf-8")
    base_url = (settings.content_storage_base_url or "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}/{key}"
    return f"/{key}"
