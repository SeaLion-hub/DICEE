"""Failed-upload spool: local and S3 backends."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import app.core.config as app_config

from ._constants import SPOOL_RETRY_COUNT_KEY, SPOOL_TIMESTAMP_KEY
from ._metadata import apply_dead_letter_metadata, apply_error_metadata

logger = logging.getLogger(__name__)

_s3_client: Any = None


def _spool_base_path() -> Path:
    return Path(app_config.settings.content_spool_dir or "storage/content_spool").resolve()


def _spool_s3_prefix() -> str:
    prefix = (app_config.settings.content_spool_s3_prefix or "content-spool").strip().strip("/")
    return prefix or "content-spool"


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
    _s3_client = boto3.client("s3", region_name=app_config.settings.s3_region)
    return _s3_client


def spool_list_s3() -> list[str]:
    bucket = (app_config.settings.s3_bucket or "").strip()
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
    bucket = (app_config.settings.s3_bucket or "").strip()
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
    bucket = (app_config.settings.s3_bucket or "").strip()
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
            **({"SSEKMSKeyId": app_config.settings.s3_sse_kms_key_id} if app_config.settings.s3_sse_kms_key_id else {}),
        )
    except Exception as e:
        logger.warning("S3 spool overwrite failed: key=%s error=%s", key, e)


def spool_delete_s3(key: str) -> None:
    bucket = (app_config.settings.s3_bucket or "").strip()
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
    bucket = (app_config.settings.s3_bucket or "").strip()
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
            **({"SSEKMSKeyId": app_config.settings.s3_sse_kms_key_id} if app_config.settings.s3_sse_kms_key_id else {}),
        )
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        logger.warning("S3 spool move to DLQ failed: key=%s dlq_key=%s error=%s", key, dlq_key, e)
        return False


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

    backend = (app_config.settings.content_spool_backend or "local").strip().lower()
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
