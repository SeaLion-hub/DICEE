"""Auth API. 구글 OAuth + JWT."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.auth import TokenPayload, TokenResponse
from app.services.auth_service import AuthError, google_login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    payload: TokenPayload,
    session: AsyncSession = Depends(get_db),
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
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
