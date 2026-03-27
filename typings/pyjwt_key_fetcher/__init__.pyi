"""Partial stubs for pyjwt-key-fetcher (wheel has no py.typed)."""

from collections.abc import Iterable, Mapping
from typing import Any

class AsyncKeyFetcher:
    _http_client: Any

    def __init__(
        self,
        valid_issuers: Iterable[str] | None = None,
        http_client: Any = None,
        cache_ttl: int = 3600,
        cache_maxsize: int = 32,
        config_path: str = "/.well-known/openid-configuration",
        static_issuer_config: dict[str, Any] | None = None,
    ) -> None: ...

    @staticmethod
    def get_kid(token: str) -> str: ...

    @staticmethod
    def get_issuer(token: str) -> str: ...

    async def get_key_by_iss_and_kid(self, iss: str, kid: str) -> Mapping[str, Any]: ...

    async def get_key(self, token: str) -> Mapping[str, Any]: ...
