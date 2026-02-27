from typing import Literal

JwtSigningMode = Literal["auto", "hs256", "rs256"]
JwtAlgorithm = Literal["HS256", "RS256"]


def normalize_jwt_signing_mode(value: str | None) -> JwtSigningMode:
    mode = (value or "auto").strip().lower()
    if mode not in {"auto", "hs256", "rs256"}:
        raise ValueError("JWT_SIGNING_MODE must be one of: auto, hs256, rs256")
    return mode  # type: ignore[return-value]


def has_hs_secret(jwt_secret: str | None) -> bool:
    return bool((jwt_secret or "").strip())


def has_complete_rs_keypair(jwt_private_key_pem: str | None, jwt_public_key_pem: str | None) -> bool:
    return bool((jwt_private_key_pem or "").strip() and (jwt_public_key_pem or "").strip())


def resolve_jwt_signing_algorithm(
    mode: str | None,
    *,
    jwt_secret: str | None,
    jwt_private_key_pem: str | None,
    jwt_public_key_pem: str | None,
) -> JwtAlgorithm:
    normalized = normalize_jwt_signing_mode(mode)
    has_hs = has_hs_secret(jwt_secret)
    has_rs = has_complete_rs_keypair(jwt_private_key_pem, jwt_public_key_pem)

    if normalized == "rs256":
        if not has_rs:
            raise ValueError("JWT_SIGNING_MODE=rs256 requires both JWT_PRIVATE_KEY_PEM and JWT_PUBLIC_KEY_PEM")
        return "RS256"

    if normalized == "hs256":
        if not has_hs:
            raise ValueError("JWT_SIGNING_MODE=hs256 requires JWT_SECRET")
        return "HS256"

    # auto mode: RS first, then HS fallback.
    if has_rs:
        return "RS256"
    if has_hs:
        return "HS256"
    raise ValueError(
        "JWT_SIGNING_MODE=auto requires either a complete RS key pair "
        "(JWT_PRIVATE_KEY_PEM + JWT_PUBLIC_KEY_PEM) or JWT_SECRET"
    )
