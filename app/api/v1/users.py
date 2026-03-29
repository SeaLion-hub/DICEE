"""로그인 유저 프로필 API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.api.v1.auth import VerifiedAccessDep
from app.core.deps import SessionDep
from app.core.exceptions import UserNotFoundError
from app.schemas.user_profile_matching import UserMeResponse, UserProfileMatchingPatch
from app.services import user_profile_service

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)

_DB_UNAVAILABLE = "User service temporarily unavailable. Try again later."


@router.get("/me", response_model=UserMeResponse)
async def get_me(
    session: SessionDep,
    access: VerifiedAccessDep,
) -> UserMeResponse:
    try:
        return await user_profile_service.get_me(session, access.user_id)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="User not found") from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        logger.warning("get_me DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e


@router.patch("/me", response_model=UserMeResponse)
async def patch_me(
    session: SessionDep,
    access: VerifiedAccessDep,
    body: UserProfileMatchingPatch,
) -> UserMeResponse:
    try:
        out = await user_profile_service.patch_me(session, access.user_id, body)
        await session.commit()
        return out
    except UserNotFoundError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="User not found") from None
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        await session.rollback()
        logger.warning("patch_me DB error: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from e
