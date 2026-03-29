"""S3 and local filesystem upload implementations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import app.core.config as app_config
from app.core.metrics import CONTENT_UPLOAD_FAILURE_TOTAL, increment

logger = logging.getLogger(__name__)


def _upload_s3_image(body_bytes: bytes, key: str, content_type: str) -> str | None:
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        logger.warning("boto3 not installed; cannot upload image to S3.")
        return None

    bucket = app_config.settings.s3_bucket
    if not bucket:
        return None

    try:
        client = boto3.client("s3", region_name=app_config.settings.s3_region)
        put_kw: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": body_bytes,
            "ContentType": content_type or "image/jpeg",
            "ServerSideEncryption": "aws:kms",
        }
        kms_key_id = app_config.settings.s3_sse_kms_key_id
        if kms_key_id and str(kms_key_id).strip():
            put_kw["SSEKMSKeyId"] = str(kms_key_id).strip()
        client.put_object(**put_kw)
        return f"https://{bucket}.s3.{app_config.settings.s3_region}.amazonaws.com/{key}"
    except ClientError as e:
        logger.exception("S3 image upload failed: key=%s error=%s", key, e)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        if (app_config.settings.content_upload_failure_policy or "").strip().lower() == "fail":
            raise
        return None


def _upload_local_image(body_bytes: bytes, key: str) -> str | None:
    base = Path(app_config.settings.content_storage_local_path or "storage/contents").resolve()
    path = (base / key).resolve()

    try:
        path.relative_to(base)
    except ValueError as e:
        logger.error("Local image path escaped base: base=%s key=%s path=%s", base, key, path)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        policy = (app_config.settings.content_upload_failure_policy or "").strip().lower()
        if policy == "fail":
            raise ValueError("Invalid image key; escaped storage base directory") from e
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body_bytes)

    base_url = (app_config.settings.content_storage_base_url or "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}/{key}"
    return f"/{key}"


def _upload_s3(html_content: str, key: str) -> str | None:
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        logger.warning("boto3 not installed; cannot upload to S3. Install boto3 or use content_storage_type=local.")
        return None

    bucket = app_config.settings.s3_bucket
    if not bucket:
        return None

    try:
        client = boto3.client("s3", region_name=app_config.settings.s3_region)
        put_kw: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": html_content.encode("utf-8"),
            "ContentType": "text/html; charset=utf-8",
            "ServerSideEncryption": "aws:kms",
        }
        kms_key_id = app_config.settings.s3_sse_kms_key_id
        if kms_key_id and str(kms_key_id).strip():
            put_kw["SSEKMSKeyId"] = str(kms_key_id).strip()
        client.put_object(**put_kw)
        return f"https://{bucket}.s3.{app_config.settings.s3_region}.amazonaws.com/{key}"
    except ClientError as e:
        logger.exception("S3 upload failed: key=%s error=%s", key, e)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        if (app_config.settings.content_upload_failure_policy or "").strip().lower() == "fail":
            raise
        return None


def _upload_local(html_content: str, key: str) -> str | None:
    base = Path(app_config.settings.content_storage_local_path or "storage/contents").resolve()
    path = (base / key).resolve()

    try:
        path.relative_to(base)
    except ValueError as e:
        logger.error("Local content path escaped base: base=%s key=%s path=%s", base, key, path)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        policy = (app_config.settings.content_upload_failure_policy or "").strip().lower()
        if policy == "fail":
            raise ValueError("Invalid content key; escaped storage base directory") from e
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_content, encoding="utf-8")

    base_url = (app_config.settings.content_storage_base_url or "").strip()
    if base_url:
        return f"{base_url.rstrip('/')}/{key}"
    return f"/{key}"
