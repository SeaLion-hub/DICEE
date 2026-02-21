"""Auth API. 구글 OAuth + JWT."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.deps import get_httpx_client
from app.schemas.auth import TokenPayload, TokenResponse
from app.services.auth_service import (
    AuthError,
    google_login,
    logout_user,
    verify_access_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    """Authorization Bearer에서 Access JWT 검증 후 user_id 반환. Swagger Authorize 정상 동작."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    try:
        payload = verify_access_token(credentials.credentials)
        return int(payload["sub"])
    except AuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    payload: TokenPayload,
    http_client: httpx.AsyncClient = Depends(get_httpx_client),
) -> TokenResponse:
    """
    구글 OAuth Authorization Code로 로그인.
    code를 받아 검증 후 Access/Refresh JWT 반환.
    """
    try:
        return await google_login(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
            http_client=http_client,
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/logout")
async def post_logout(
    user_id: int = Depends(get_current_user_id),
) -> None:
    """
    로그아웃. 해당 유저의 refresh_token_version 증가 → 기존 Refresh 토큰 전부 무효화.
    Authorization: Bearer <access_token> 필요.
    """
    await logout_user(user_id)
