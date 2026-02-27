"""Auth Service. 援ш? OAuth code 寃利? User upsert, JWT 諛쒓툒."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, cast
from urllib.parse import unquote, urlparse

import httpx
import jwt
from pydantic import ValidationError
from pyjwt_key_fetcher import AsyncKeyFetcher
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.jwt import resolve_jwt_signing_algorithm
from app.core.ip_hmac import compute_ip_hmac
from app.core.redis import is_access_blocked
from app.repositories.login_audit_repository import create_login_audit
from app.repositories.user_repository import (
    increment_refresh_token_version,
    rotate_refresh_token_version,
    upsert_by_provider_uid,
)
from app.schemas.auth import GoogleTokenResponse, TokenResponse
from app.schemas.user import UserBase

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """?대씪?댁뼵???몄쬆/沅뚰븳 ?ㅻ쪟. Router?먯꽌 400 ?먮뒗 401濡?蹂??"""

    pass


class AuthServiceUnavailableError(Exception):
    """?몃? ?몄쬆 ?쒓났??援ш? ?? ?쇱떆 遺덇?. Router?먯꽌 503 Service Unavailable濡?蹂??"""

    pass


async def exchange_google_code(
    code: str,
    redirect_uri: str | None,
    client: httpx.AsyncClient,
) -> GoogleTokenResponse:
    """
    援ш? OAuth Authorization Code瑜??≪꽭???좏겙?쇰줈 援먰솚.
    Pydantic ?ㅽ궎留덈줈 寃利? ?ㅽ듃?뚰겕 ?덉쇅(Timeout, Connect) ??AuthServiceUnavailableError(503)濡?蹂??
    """
    client_secret = settings.google_client_secret.get_secret_value()
    try:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri or "http://localhost",
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ) as e:
        logger.warning("Google token exchange network error: %s", e, exc_info=True)
        raise AuthServiceUnavailableError("Google auth temporarily unavailable") from e
    if resp.status_code != 200:
        logger.warning(
            "Google token exchange failed: status=%s body=%s",
            resp.status_code,
            (resp.text[:200] if resp.text else ""),
        )
        raise AuthError("Invalid or expired authorization code")

    data = resp.json()
    try:
        return GoogleTokenResponse.model_validate(data)
    except ValidationError as e:
        raise AuthError("Invalid Google token response") from e


async def decode_google_id_token(
    id_token_str: str, key_fetcher: AsyncKeyFetcher
) -> dict[str, Any]:
    """援ш? ID token ?쒕챸 寃利????붿퐫?? key_fetcher??lifespan ?깃???Depends)."""
    try:
        key_entry = await key_fetcher.get_key(id_token_str)
        payload = jwt.decode(
            jwt=id_token_str,
            audience=settings.google_client_id,
            options={"verify_exp": True, "verify_aud": True},
            **key_entry,
        )
        return cast(dict[str, Any], payload)
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid id_token: %s", e)
        raise AuthError("Invalid id_token") from e
    except Exception as e:
        logger.warning("ID token verification failed (JWKS/network): %s", e, exc_info=True)
        raise AuthServiceUnavailableError(
            "ID token verification temporarily unavailable"
        ) from e


def _jwt_encode_key_and_algorithm() -> tuple[str | bytes, str]:
    """Resolve encode algorithm/key using JWT_SIGNING_MODE."""
    private_key = (
        settings.jwt_private_key_pem.get_secret_value()
        if settings.jwt_private_key_pem
        else None
    )
    public_key = (
        settings.jwt_public_key_pem.get_secret_value()
        if settings.jwt_public_key_pem
        else None
    )
    secret = settings.jwt_secret.get_secret_value()
    try:
        algorithm = resolve_jwt_signing_algorithm(
            settings.jwt_signing_mode,
            jwt_secret=secret,
            jwt_private_key_pem=private_key,
            jwt_public_key_pem=public_key,
        )
    except ValueError as e:
        raise AuthError(str(e)) from e

    if algorithm == "RS256":
        assert private_key is not None
        return private_key.strip(), "RS256"
    return secret, "HS256"


def _jwt_decode_key_and_algorithm() -> tuple[str | bytes, str]:
    """Resolve decode algorithm/key using JWT_SIGNING_MODE."""
    private_key = (
        settings.jwt_private_key_pem.get_secret_value()
        if settings.jwt_private_key_pem
        else None
    )
    public_key = (
        settings.jwt_public_key_pem.get_secret_value()
        if settings.jwt_public_key_pem
        else None
    )
    secret = settings.jwt_secret.get_secret_value()
    try:
        algorithm = resolve_jwt_signing_algorithm(
            settings.jwt_signing_mode,
            jwt_secret=secret,
            jwt_private_key_pem=private_key,
            jwt_public_key_pem=public_key,
        )
    except ValueError as e:
        raise AuthError(str(e)) from e

    if algorithm == "RS256":
        assert public_key is not None
        return public_key.strip(), "RS256"
    return secret, "HS256"


def create_jwt_pair(user_id: uuid.UUID, token_version: int = 0) -> tuple[str, str]:
    """
    Access + Refresh JWT ?앹꽦. Access?먮뒗 jti ?ы븿(Blocklist 臾댄슚?붿슜).
    token_version: 濡쒓렇?꾩썐/?덉랬 ???쒕쾭?먯꽌 臾댄슚?뷀븯湲??꾪빐 User.refresh_token_version怨??곕룞.
    RS256 ?ㅺ? ?ㅼ젙?섎㈃ RS256, ?꾨땲硫?HS256 ?ъ슜.
    """
    key, algorithm = _jwt_encode_key_and_algorithm()
    now = datetime.now(UTC)
    access_payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(seconds=settings.jwt_access_expire_seconds),
        "iat": now,
    }
    refresh_payload = {
        "sub": str(user_id),
        "type": "refresh",
        "token_version": token_version,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(days=settings.jwt_refresh_expire_days),
        "iat": now,
    }
    access_token = jwt.encode(access_payload, key, algorithm=algorithm)
    refresh_token = jwt.encode(refresh_payload, key, algorithm=algorithm)
    return access_token, refresh_token


async def verify_access_token(
    encoded: str,
    redis_blocklist_client: RedisAsyncio | None = None,
    *,
    fail_closed: bool = True,
) -> dict[str, Any]:
    """
    Access JWT 寃利? iss/aud/type=access ?뺤씤 ??Blocklist 議고쉶.
    Redis ?μ븷 ?? fail_closed=True硫??몄쬆 嫄곕?, False硫??쒕챸留?誘욧퀬 ?듦낵.
    RS256 ?ㅺ? ?ㅼ젙?섎㈃ RS256, ?꾨땲硫?HS256?쇰줈 寃利?
    """
    key, algorithm = _jwt_decode_key_and_algorithm()
    try:
        payload = jwt.decode(
            encoded,
            key,
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "type", "jti"]},
        )
        if payload.get("type") != "access":
            raise AuthError("Invalid token type")
        jti = payload.get("jti")
        if redis_blocklist_client is not None and jti:
            blocked = await is_access_blocked(
                redis_blocklist_client, jti, fail_closed=fail_closed
            )
            if blocked:
                raise AuthError("Token revoked or invalid")
        return cast(dict[str, Any], payload)
    except AuthError:
        raise
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid access token: %s", e)
        raise AuthError("Invalid or expired token") from e


def verify_refresh_token(encoded: str) -> dict[str, Any]:
    """
    Refresh JWT 寃利? type=refresh, token_version, sub, exp ?꾩닔.
    遺덉씪移?留뚮즺 ??AuthError. 諛섑솚 payload?먮뒗 sub, token_version ?ы븿.
    """
    key, algorithm = _jwt_decode_key_and_algorithm()
    try:
        payload = jwt.decode(
            encoded,
            key,
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "type", "token_version"]},
        )
        if payload.get("type") != "refresh":
            raise AuthError("Invalid token type")
        return cast(dict[str, Any], payload)
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid refresh token: %s", e)
        raise AuthError("Invalid or expired refresh token") from e


async def refresh_tokens(
    refresh_token: str,
    session: AsyncSession,
) -> TokenResponse:
    """
    Refresh ?좏겙?쇰줈 ??Access/Refresh ??諛쒓툒. 1?뚯꽦: ?먯옄??CAS ?뚯쟾 ????version?쇰줈 諛쒓툒.
    ?대? ?ъ슜???좏겙 ?먮뒗 踰꾩쟾 遺덉씪移???AuthError(臾댄슚?붾맂 ?좏겙).
    """
    payload = verify_refresh_token(refresh_token)
    user_id = uuid.UUID(payload["sub"])
    token_version = int(payload["token_version"])
    new_version = await rotate_refresh_token_version(session, user_id, token_version)
    if new_version is None:
        raise AuthError("Refresh token revoked or invalid")
    access_token, new_refresh_token = create_jwt_pair(user_id, token_version=new_version)
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_expire_seconds,
    )


async def revoke_refresh_tokens_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    """?대떦 ?좎???refresh_token_version 利앷? ??湲곗〈 Refresh ?좏겙 ?꾨? 臾댄슚??"""
    await increment_refresh_token_version(session, user_id)


def _normalize_redirect_uri(uri: str) -> str:
    """
    redirect_uri ?뺢퇋?? scheme쨌host ?뚮Ц?? path ??踰덈쭔 unquote, query쨌fragment쨌userinfo 嫄곕?.
    ?붾툝 ?몄퐫??諛⑹뼱: unquote 1????path??'%'媛 ?⑥븘 ?덉쑝硫?嫄곕?.
    """
    s = (uri or "").strip()
    if not s:
        raise AuthError("redirect_uri required")
    parsed = urlparse(s)
    if (parsed.scheme or "").lower() not in ("http", "https"):
        raise AuthError("redirect_uri must be http or https")
    if parsed.username or parsed.password or not parsed.hostname:
        raise AuthError("redirect_uri host is invalid")
    if parsed.query or parsed.fragment:
        raise AuthError("redirect_uri must not contain query or fragment")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port else ""
    path = (unquote(parsed.path or "/").rstrip("/") or "/")
    if "%" in path:
        raise AuthError("redirect_uri invalid encoding")
    return f"{parsed.scheme.lower()}://{host}{port}{path}"


@lru_cache(maxsize=1)
def _allowed_redirect_uris() -> set[str]:
    """
    ?ㅼ젙???덉슜 redirect_uri 紐⑸줉(?쇳몴 援щ텇). ?뺢퇋????set 諛섑솚. 鍮꾩뼱 ?덉쑝硫?鍮?set.
    P0 fail-closed: ?ㅼ젙媛믪씠 ?덈뒗???좏슚??URI媛 ?섎굹???놁쑝硫?AuthError. ?덉슜 紐⑸줉??鍮꾨㈃ 寃利??앸왂?섏? ?딆쓬.
    """
    raw = (settings.google_redirect_uris or "").strip()
    if not raw:
        return set()
    result: set[str] = set()
    for u in raw.split(","):
        u = u.strip()
        if not u:
            continue
        try:
            result.add(_normalize_redirect_uri(u))
        except AuthError:
            continue
    if not result:
        raise AuthError(
            "google_redirect_uris: no valid redirect URIs (all entries invalid or malformed). Fix configuration."
        )
    return result


async def google_login(
    session: AsyncSession,
    code: str,
    redirect_uri: str | None = None,
    *,
    http_client: httpx.AsyncClient,
    key_fetcher: AsyncKeyFetcher,
    client_ip: str | None = None,
) -> TokenResponse:
    """
    援ш? OAuth code濡?濡쒓렇?? redirect_uri allowlist쨌sub ?대젅???꾩닔 寃利?Fail-fast).
    1. redirect_uri ?덉슜 紐⑸줉 寃???ㅼ젙 ??
    2. code ??援ш? ?좏겙 援먰솚
    3. id_token JWKS 寃利????꾨줈??異붿텧, sub ?꾩닔(?꾨씫 ??AuthError)
    4. User upsert, JWT 諛쒓툒
    ?몃옖??뀡 寃쎄퀎???몄텧???쇱슦??媛 ?뚯쑀. session? Depends(get_db)濡?二쇱엯諛쏆븘 ?ъ슜.
    """
    allowed = _allowed_redirect_uris()
    if allowed:
        try:
            normalized = _normalize_redirect_uri(redirect_uri or "")
        except AuthError:
            raise
        if normalized not in allowed:
            raise AuthError("redirect_uri not allowed")
    else:
        # ?ㅼ젙 誘몄궗???쒖뿉留?寃???앸왂. (google_redirect_uris 鍮꾩뼱 ?덉쓬. ?꾨줈?뺤뀡?먯꽌???ㅼ젙 沅뚯옣.)
        normalized = redirect_uri or "http://localhost"
    token_data = await exchange_google_code(code, normalized, http_client)
    id_token = token_data.id_token

    claims = await decode_google_id_token(id_token, key_fetcher)
    provider_user_id = claims.get("sub")
    if not provider_user_id or not str(provider_user_id).strip():
        raise AuthError("Invalid id_token: missing sub")
    provider_user_id = str(provider_user_id).strip()
    email = claims.get("email")
    name = claims.get("name")

    user_base = UserBase(email=email, name=name, profile_json=None)

    user = await upsert_by_provider_uid(
        session, "google", provider_user_id, user_base
    )

    if client_ip:
        ip_hmac_val, ip_hmac_key_version = compute_ip_hmac(client_ip)
        await create_login_audit(
            session,
            ip_hmac=ip_hmac_val,
            ip_hmac_key_version=ip_hmac_key_version,
            user_id=user.id,
            provider="google",
        )

    version = getattr(user, "refresh_token_version", 0)
    access_token, refresh_token = create_jwt_pair(user.id, token_version=version)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_expire_seconds,
    )


async def logout_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """
    濡쒓렇?꾩썐 DB ?④퀎留??섑뻾: Refresh 臾댄슚??refresh_token_version 利앷?).
    ?몄텧?먭? 諛섎뱶??session.commit() ??Redis Blocklist瑜??쒕룄?댁빞 ??
    ?쒖꽌: logout_user ??commit ??blocklist. 洹몃옒??Redis ?ㅽ뙣 ?쒖뿉??DB???대? ?뺤젙?섏뼱 ?ъ떆????Blocklist留??щ벑濡?
    """
    await revoke_refresh_tokens_for_user(session, user_id)

