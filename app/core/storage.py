"""Notice content storage and failed-upload spool backends."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.metrics import CONTENT_UPLOAD_FAILURE_TOTAL, increment

logger = logging.getLogger(__name__)

SPOOL_RETRY_COUNT_KEY = "retry_count"
SPOOL_TIMESTAMP_KEY = "timestamp"
SPOOL_LAST_ERROR_TYPE_KEY = "last_error_type"
SPOOL_LAST_ERROR_MESSAGE_KEY = "last_error_message"
SPOOL_LAST_ERROR_AT_KEY = "last_error_at"
SPOOL_LAST_ERROR_STAGE_KEY = "last_error_stage"
SPOOL_DEAD_LETTERED_AT_KEY = "dead_lettered_at"
SPOOL_DEAD_LETTER_REASON_KEY = "dead_letter_reason"

SPOOL_LAST_ERROR_MESSAGE_MAX_LEN = 500


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_error_message(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    msg = str(error)
    if len(msg) > SPOOL_LAST_ERROR_MESSAGE_MAX_LEN:
        return msg[:SPOOL_LAST_ERROR_MESSAGE_MAX_LEN]
    return msg


def apply_error_metadata(
    entry: dict[str, Any],
    *,
    error: BaseException | str | None,
    stage: str,
    retry_count: int | None = None,
) -> dict[str, Any]:
    updated = dict(entry)
    if retry_count is not None:
        updated[SPOOL_RETRY_COUNT_KEY] = max(0, int(retry_count))

    err_type: str | None
    if isinstance(error, BaseException):
        err_type = type(error).__name__
    elif isinstance(error, str) and error:
        err_type = "Error"
    else:
        err_type = None

    updated[SPOOL_LAST_ERROR_TYPE_KEY] = err_type
    updated[SPOOL_LAST_ERROR_MESSAGE_KEY] = _safe_error_message(error)
    updated[SPOOL_LAST_ERROR_AT_KEY] = _utc_now_iso()
    updated[SPOOL_LAST_ERROR_STAGE_KEY] = stage
    return updated


def apply_dead_letter_metadata(entry: dict[str, Any], *, reason: str) -> dict[str, Any]:
    updated = dict(entry)
    updated[SPOOL_DEAD_LETTERED_AT_KEY] = _utc_now_iso()
    updated[SPOOL_DEAD_LETTER_REASON_KEY] = reason
    return updated


def upload_notice_html(
    html_content: str | None,
    *,
    college_id: uuid.UUID,
    external_id: str,
    content_hash: str | None = None,
) -> str | None:
    """Upload notice HTML and return content URL."""
    content = (html_content or "").strip()
    if not content:
        return None

    key = _object_key(college_id, external_id, content_hash)
    try:
        if (settings.content_storage_type or "").lower() == "s3" and settings.s3_bucket:
            return _upload_s3(content, key)
        return _upload_local(content, key)
    except Exception as e:
        if (settings.content_upload_failure_policy or "").strip().lower() == "fail":
            _spool_write_failure(
                college_id,
                external_id,
                content_hash,
                content,
                retry_count=0,
                last_error=e,
                last_error_stage="upload",
            )
        raise


def _sanitize_external_id_for_key(external_id: str, *, fallback_seed: str | None = None) -> str:
    raw = (external_id or "").strip()
    if not raw:
        if fallback_seed:
            digest = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:8]
            return f"unknown_{digest}"
        return "unknown"

    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    while ".." in safe:
        safe = safe.replace("..", "_")
    safe = re.sub(r"_+", "_", safe).strip("_")

    if not safe:
        if fallback_seed:
            digest = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:8]
            return f"unknown_{digest}"
        return "unknown"

    max_len = 150
    if len(safe) > max_len:
        digest = hashlib.sha256(safe.encode("utf-8")).hexdigest()[:8]
        prefix = safe[: max_len - 1 - len(digest)]
        safe = f"{prefix}_{digest}"

    return safe


def _object_key(college_id: uuid.UUID, external_id: str, content_hash: str | None) -> str:
    ext_for_hash = external_id or ""
    digest = (content_hash or hashlib.sha256((str(college_id) + ext_for_hash).encode()).hexdigest())[:16]
    safe_ext = _sanitize_external_id_for_key(ext_for_hash, fallback_seed=f"{college_id}_{digest}")
    prefix = (settings.s3_content_prefix or "").strip().strip("/")
    if prefix:
        return f"{prefix}/{college_id}/{digest}_{safe_ext}.html"
    return f"{college_id}/{digest}_{safe_ext}.html"


def _upload_s3(html_content: str, key: str) -> str | None:
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
        put_kw: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": html_content.encode("utf-8"),
            "ContentType": "text/html; charset=utf-8",
            "ServerSideEncryption": "aws:kms",
        }
        kms_key_id = settings.s3_sse_kms_key_id
        if kms_key_id and str(kms_key_id).strip():
            put_kw["SSEKMSKeyId"] = str(kms_key_id).strip()
        client.put_object(**put_kw)
        return f"https://{bucket}.s3.{settings.s3_region}.amazonaws.com/{key}"
    except ClientError as e:
        logger.exception("S3 upload failed: key=%s error=%s", key, e)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        if (settings.content_upload_failure_policy or "").strip().lower() == "fail":
            raise
        return None


def _upload_local(html_content: str, key: str) -> str | None:
    base = Path(settings.content_storage_local_path or "storage/contents").resolve()
    path = (base / key).resolve()

    try:
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


def _spool_base_path() -> Path:
    return Path(settings.content_spool_dir or "storage/content_spool").resolve()


def _spool_s3_prefix() -> str:
    prefix = (settings.content_spool_s3_prefix or "content-spool").strip().strip("/")
    return prefix or "content-spool"


def _spool_write_failure(
    college_id: uuid.UUID,
    external_id: str,
    content_hash: str | None,
    html_content: str,
    *,
    retry_count: int = 0,
    last_error: BaseException | str | None = None,
    last_error_stage: str = "upload",
) -> None:
    import time

    ts = int(time.time() * 1000)
    payload: dict[str, Any] = {
        "college_id": str(college_id),
        "external_id": external_id,
        "content_hash": content_hash,
        "html_content": html_content,
        SPOOL_TIMESTAMP_KEY: ts,
        SPOOL_RETRY_COUNT_KEY: retry_count,
    }
    payload = apply_error_metadata(
        payload,
        error=last_error,
        stage=last_error_stage,
        retry_count=retry_count,
    )

    backend = (settings.content_spool_backend or "local").strip().lower()
    if backend == "s3":
        key = f"{_spool_s3_prefix()}/{ts}_{uuid.uuid4().hex[:8]}.json"
        spool_overwrite_s3(key, payload)
        return

    base = _spool_base_path()
    name = f"{ts}_{uuid.uuid4().hex[:8]}.json"
    path = (base / name).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        logger.error("Spool path escaped base: base=%s name=%s path=%s", base, name, path)
        return
    try:
        base.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.exception("Spool write failed: path=%s error=%s", path, e)


def spool_list_local() -> list[Path]:
    base = _spool_base_path()
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.iterdir():
        if p.suffix != ".json" or not p.is_file():
            continue
        try:
            p.resolve().relative_to(base)
        except ValueError:
            continue
        out.append(p)
    return sorted(out, key=lambda x: x.name)


def spool_read_entry(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "college_id" in data and "external_id" in data and "html_content" in data:
            return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Spool read failed: path=%s error=%s", path, e)
    return None


def spool_overwrite_entry(path: Path, entry: dict[str, Any]) -> None:
    base = _spool_base_path()
    try:
        path.resolve().relative_to(base)
    except ValueError:
        logger.error("Spool overwrite path escaped base: path=%s base=%s", path, base)
        return
    try:
        path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.warning("Spool overwrite failed: path=%s error=%s", path, e)


def spool_delete_local(path: Path) -> None:
    path.unlink(missing_ok=True)


def spool_move_to_dlq_local(path: Path, entry: dict[str, Any], *, reason: str) -> bool:
    base = _spool_base_path()
    dlq_dir = base.parent / (base.name + "_dlq")
    try:
        dlq_dir.mkdir(parents=True, exist_ok=True)
        dest = dlq_dir / path.name
        payload = apply_dead_letter_metadata(entry, reason=reason)
        dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        path.unlink(missing_ok=True)
        return True
    except OSError:
        logger.exception("Spool local move to DLQ failed: path=%s reason=%s", path, reason)
        return False


_s3_client: Any = None


def _build_s3_client():
    """Lazy singleton S3 client. Reused across spool/upload calls to avoid connection churn."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 not installed; S3 spool backend unavailable")
        return None
    _s3_client = boto3.client("s3", region_name=settings.s3_region)
    return _s3_client


def spool_list_s3() -> list[str]:
    bucket = (settings.s3_bucket or "").strip()
    if not bucket:
        return []
    client = _build_s3_client()
    if client is None:
        return []

    prefix = _spool_s3_prefix().rstrip("/") + "/"
    keys: list[str] = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if not key or not key.endswith(".json"):
                    continue
                if "/dlq/" in key:
                    continue
                keys.append(key)
    except Exception as e:
        logger.warning("S3 spool list failed: bucket=%s prefix=%s error=%s", bucket, prefix, e)
        return []
    return sorted(keys)


def spool_read_s3(key: str) -> dict[str, Any] | None:
    bucket = (settings.s3_bucket or "").strip()
    if not bucket:
        return None
    client = _build_s3_client()
    if client is None:
        return None
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read().decode("utf-8")
        data = json.loads(body)
        if isinstance(data, dict) and "college_id" in data and "external_id" in data and "html_content" in data:
            return data
    except Exception as e:
        logger.warning("S3 spool read failed: key=%s error=%s", key, e)
    return None


def spool_overwrite_s3(key: str, entry: dict[str, Any]) -> None:
    bucket = (settings.s3_bucket or "").strip()
    if not bucket:
        return
    client = _build_s3_client()
    if client is None:
        return
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(entry, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="aws:kms",
            **({"SSEKMSKeyId": settings.s3_sse_kms_key_id} if settings.s3_sse_kms_key_id else {}),
        )
    except Exception as e:
        logger.warning("S3 spool overwrite failed: key=%s error=%s", key, e)


def spool_delete_s3(key: str) -> None:
    bucket = (settings.s3_bucket or "").strip()
    if not bucket:
        return
    client = _build_s3_client()
    if client is None:
        return
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except Exception as e:
        logger.warning("S3 spool delete failed: key=%s error=%s", key, e)


def spool_move_to_dlq_s3(key: str, entry: dict[str, Any], *, reason: str) -> bool:
    bucket = (settings.s3_bucket or "").strip()
    if not bucket:
        return False
    client = _build_s3_client()
    if client is None:
        return False

    filename = key.rsplit("/", 1)[-1]
    dlq_key = f"{_spool_s3_prefix().rstrip('/')}/dlq/{filename}"
    payload = apply_dead_letter_metadata(entry, reason=reason)

    try:
        client.put_object(
            Bucket=bucket,
            Key=dlq_key,
            Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="aws:kms",
            **({"SSEKMSKeyId": settings.s3_sse_kms_key_id} if settings.s3_sse_kms_key_id else {}),
        )
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        logger.warning("S3 spool move to DLQ failed: key=%s dlq_key=%s error=%s", key, dlq_key, e)
        return False
