import json


def _parse_allowed_origins(value: str) -> list[str]:
    if not value or not value.strip():
        return []
    s = value.strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"ALLOWED_ORIGINS invalid JSON: {e}") from e
        if not isinstance(parsed, list):
            raise ValueError("ALLOWED_ORIGINS must be a JSON array.")
        origins = [str(x).strip() for x in parsed if str(x).strip()]
    else:
        origins = [x.strip() for x in s.split(",") if x.strip()]
    for origin in origins:
        if origin == "*":
            raise ValueError(
                "ALLOWED_ORIGINS cannot contain '*' when allow_credentials is True. "
                "Specify explicit origins (JSON array or comma-separated)."
            )
        if not (origin.startswith("http://") or origin.startswith("https://")):
            raise ValueError(f"ALLOWED_ORIGINS entry must be http(s) URL: {origin!r}")
    return origins
