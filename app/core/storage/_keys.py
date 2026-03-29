"""S3/local object key generation."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import app.core.config as app_config

_IMAGE_EXT_FROM_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


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
    prefix = (app_config.settings.s3_content_prefix or "").strip().strip("/")
    if prefix:
        return f"{prefix}/{college_id}/{digest}_{safe_ext}.html"
    return f"{college_id}/{digest}_{safe_ext}.html"


def _image_extension(filename_hint: str | None, content_type: str | None) -> str:
    if filename_hint:
        suf = Path(filename_hint).suffix.lstrip(".").lower()
        if suf in ("jpg", "jpeg", "png", "gif", "webp"):
            return "jpg" if suf == "jpeg" else suf
    if content_type:
        return _IMAGE_EXT_FROM_MIME.get(content_type.strip().lower(), "jpg")
    return "jpg"


def _object_key_image(
    college_id: uuid.UUID,
    external_id: str,
    index: int,
    ext: str,
) -> str:
    safe_ext = _sanitize_external_id_for_key(external_id or "", fallback_seed=str(college_id))
    short = hashlib.sha256(f"{college_id}{external_id}{index}".encode()).hexdigest()[:8]
    prefix = (app_config.settings.s3_content_prefix or "").strip().strip("/")
    if prefix:
        return f"{prefix}/{college_id}/{safe_ext}/images/{index}_{short}.{ext}"
    return f"{college_id}/{safe_ext}/images/{index}_{short}.{ext}"
