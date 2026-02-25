"""공지 본문 스토리지. S3 또는 로컬에 저장 후 content_url 반환."""

import hashlib
import logging
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


def _object_key(college_id: uuid.UUID, external_id: str, content_hash: str | None) -> str:
    """스토리지 객체 키. 동일 college+external_id면 덮어쓰기."""
    safe_ext = (external_id or "").replace("/", "_")[:200]
    h = (content_hash or hashlib.sha256((str(college_id) + external_id).encode()).hexdigest())[:16]
    return f"{settings.s3_content_prefix}/{college_id}/{h}_{safe_ext}.html"


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
    base = Path(settings.content_storage_local_path or "storage/contents")
    path = base / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_content, encoding="utf-8")
    base_url = (settings.content_storage_base_url or "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}/{key}"
    return f"/{key}"
