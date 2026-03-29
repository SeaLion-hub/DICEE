"""Public upload entry points for notice HTML and images."""

from __future__ import annotations

import logging
import uuid

import app.core.config as app_config
from app.core.metrics import CONTENT_UPLOAD_FAILURE_TOTAL, increment

from ._backends import _upload_local, _upload_local_image, _upload_s3, _upload_s3_image
from ._keys import _image_extension, _object_key, _object_key_image
from ._spool_ops import _spool_write_failure

logger = logging.getLogger(__name__)


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
        if (app_config.settings.content_storage_type or "").lower() == "s3" and app_config.settings.s3_bucket:
            return _upload_s3(content, key)
        return _upload_local(content, key)
    except Exception as e:
        if (app_config.settings.content_upload_failure_policy or "").strip().lower() == "fail":
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


def upload_notice_image(
    image_bytes: bytes,
    *,
    college_id: uuid.UUID,
    external_id: str,
    index: int,
    content_type: str | None = None,
    filename_hint: str | None = None,
) -> str | None:
    """Upload notice image bytes to storage; return public URL or None on failure."""
    if not image_bytes:
        return None
    ext = _image_extension(filename_hint, content_type)
    key = _object_key_image(college_id, external_id, index, ext)
    try:
        if (app_config.settings.content_storage_type or "").lower() == "s3" and app_config.settings.s3_bucket:
            return _upload_s3_image(image_bytes, key, content_type or "image/jpeg")
        return _upload_local_image(image_bytes, key)
    except Exception as e:
        logger.warning("upload_notice_image failed: key=%s error=%s", key, e, exc_info=True)
        increment(CONTENT_UPLOAD_FAILURE_TOTAL)
        if (app_config.settings.content_upload_failure_policy or "").strip().lower() == "fail":
            raise
        return None
