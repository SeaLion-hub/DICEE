"""Health check 엔드포인트."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    """헬스 체크. 200 + {"status":"ok"}."""
    return {"status": "ok"}
