"""프로덕션 로깅 보안. 예외 traceback 원천 차단(포매터/필터)."""

import logging

from app.core.config import settings


class ProductionExceptionFilter(logging.Filter):
    """
    프로덕션에서 exc_info(스택)·예외 메시지가 로그에 누출되지 않도록 차단.
    record.exc_info 제거 + record.msg/args 덮어쓰기로 포매터가 민감 정보를 출력하지 않도록 함.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if (settings.environment or "").strip().lower() != "production":
            return True
        exc_info = getattr(record, "exc_info", None)
        if exc_info is not None:
            exc_type_name = "Unknown"
            if exc_info and len(exc_info) >= 1 and exc_info[0] is not None:
                exc_type_name = getattr(exc_info[0], "__name__", str(exc_info[0]))
            record.exc_info = None
            record.exc_text = None
            record.msg = "Internal error (%s)" % exc_type_name
            record.args = ()
        return True
