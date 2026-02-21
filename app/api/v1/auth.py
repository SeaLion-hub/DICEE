"""Auth API. 구글 OAuth + JWT."""

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_httpx_client
from app.schemas.auth import TokenPayload, TokenResponse
from app.services.auth_service import (
    AuthError,
    google_login,
    revoke_refresh_tokens_for_user,
    verify_access_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_current_user_id(
    authorization: str | None = Header(None, alias="Authorization"),
) -> int:
    """Authorization Bearer에서 Access JWT 검증 후 user_id 반환. 로그아웃·인가용."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    token = authorization[7:].strip()
    try:
        payload = verify_access_token(token)
        return int(payload["sub"])
    except AuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    payload: TokenPayload,
    session: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_httpx_client),
) -> TokenResponse:
    """
    구글 OAuth Authorization Code로 로그인.
    code를 받아 검증 후 Access/Refresh JWT 반환.
    """
    try:
        return await google_login(
            session,
            code=payload.code,
            redirect_uri=payload.redirect_uri,
            http_client=http_client,
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/logout")
async def post_logout(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> None:
    """
    로그아웃. 해당 유저의 refresh_token_version 증가 → 기존 Refresh 토큰 전부 무효화.
    Authorization: Bearer <access_token> 필요.
    """
    await revoke_refresh_tokens_for_user(session, user_id)
