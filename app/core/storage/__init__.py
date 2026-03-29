"""Notice content storage and failed-upload spool backends.

Compatibility: `from app.core.storage import upload_notice_html` and
`from app.core import storage` (``storage.settings`` for tests) unchanged.
"""

from __future__ import annotations

import app.core.config as _app_config_module

from ._backends import _upload_local, _upload_local_image, _upload_s3, _upload_s3_image
from ._constants import (
    SPOOL_DEAD_LETTER_REASON_KEY,
    SPOOL_DEAD_LETTERED_AT_KEY,
    SPOOL_LAST_ERROR_AT_KEY,
    SPOOL_LAST_ERROR_MESSAGE_KEY,
    SPOOL_LAST_ERROR_MESSAGE_MAX_LEN,
    SPOOL_LAST_ERROR_STAGE_KEY,
    SPOOL_LAST_ERROR_TYPE_KEY,
    SPOOL_RETRY_COUNT_KEY,
    SPOOL_TIMESTAMP_KEY,
)
from ._keys import (
    _image_extension,
    _object_key,
    _object_key_image,
    _sanitize_external_id_for_key,
)
from ._metadata import apply_dead_letter_metadata, apply_error_metadata
from ._spool_ops import (
    _build_s3_client,
    _spool_write_failure,
    spool_delete_local,
    spool_delete_s3,
    spool_list_local,
    spool_list_s3,
    spool_move_to_dlq_local,
    spool_move_to_dlq_s3,
    spool_overwrite_entry,
    spool_overwrite_s3,
    spool_read_entry,
    spool_read_s3,
)
from ._uploads import upload_notice_html, upload_notice_image


def __getattr__(name: str):
    if name == "settings":
        return _app_config_module.settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SPOOL_DEAD_LETTERED_AT_KEY",
    "SPOOL_DEAD_LETTER_REASON_KEY",
    "SPOOL_LAST_ERROR_AT_KEY",
    "SPOOL_LAST_ERROR_MESSAGE_KEY",
    "SPOOL_LAST_ERROR_MESSAGE_MAX_LEN",
    "SPOOL_LAST_ERROR_STAGE_KEY",
    "SPOOL_LAST_ERROR_TYPE_KEY",
    "SPOOL_RETRY_COUNT_KEY",
    "SPOOL_TIMESTAMP_KEY",
    "apply_dead_letter_metadata",
    "apply_error_metadata",
    "settings",
    "spool_delete_local",
    "spool_delete_s3",
    "spool_list_local",
    "spool_list_s3",
    "spool_move_to_dlq_local",
    "spool_move_to_dlq_s3",
    "spool_overwrite_entry",
    "spool_overwrite_s3",
    "spool_read_entry",
    "spool_read_s3",
    "upload_notice_html",
    "upload_notice_image",
    "_build_s3_client",
    "_spool_write_failure",
    "_image_extension",
    "_object_key",
    "_object_key_image",
    "_sanitize_external_id_for_key",
    "_upload_local",
    "_upload_local_image",
    "_upload_s3",
    "_upload_s3_image",
]
