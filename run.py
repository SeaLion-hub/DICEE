"""로컬 실행 스크립트. Windows에서 psycopg 호환을 위해 이벤트 루프 정책을 먼저 설정."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# uvicorn이 app.main:app 로드 전에 발생하는 예외 수집: 최소 Sentry 부트스트랩 + excepthook
_original_excepthook = sys.excepthook


def _bootstrap_sentry_and_excepthook() -> None:
    """설정 로드 후 SENTRY_DSN이 있으면 최소 초기화, excepthook으로 앱 팩토리 실행 전 예외 수집."""
    try:
        from app.core.config import settings
        if settings.sentry_dsn:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.sentry_dsn.get_secret_value(),
                environment=settings.environment,
            )

        def _excepthook(typ, value, tb):
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(value)
            except Exception:
                pass
            _original_excepthook(typ, value, tb)

        sys.excepthook = _excepthook
    except Exception:
        pass


if __name__ == "__main__":
    _bootstrap_sentry_and_excepthook()

    import uvicorn
    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
        )
    except Exception as e:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        raise
