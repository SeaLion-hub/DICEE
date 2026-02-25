"""Redis 비동기 클라이언트. Blocklist(Access Token 무효화)용. 풀 크기 명시로 동시 처리량 대응."""

import asyncio
import hashlib
import json
import logging
import ssl
import time
import uuid

from redis.asyncio import Redis as RedisAsyncio

from app.core.config import settings
from app.core.metrics import (
    LOCK_ACQUIRE_TOTAL,
    LOCK_CONFLICT_TOTAL,
    increment,
)

logger = logging.getLogger(__name__)

BLOCKLIST_KEY_PREFIX = "dicee:blocklist:access:"
TRIGGER_IDEMPOTENCY_KEY_PREFIX = "dicee:trigger_idempotency:"
TRIGGER_IDEMPOTENCY_TTL_SECONDS = 86400  # 24h

# 단과대별 크롤 트리거 분산락. TTL 내 중복 enqueue 방지. 워커 완료 시 조기 해제.
# 좀비 락 복구: 워커 하드 킬/파티션 시 TTL 만료로만 해제. Compare-and-del은 정상 종료 시 타인 락 삭제 방지용.
TRIGGER_LOCK_KEY_PREFIX = "dicee:trigger_lock:"
# TTL은 config.redis_trigger_lock_ttl_seconds 사용. 기본 2400 (max_countdown + safety_margin).

# Lua: 값이 token일 때만 삭제 (소유권 검증). 1=삭제됨, 0=소유자 아님/키 없음.
LUA_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

# Lua: 값이 token일 때만 TTL 갱신 (heartbeat). 1=갱신됨, 0=소유자 아님/키 없음.
LUA_RENEW_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
"""


class RedisLockUnavailableError(Exception):
    """Redis 인프라 오류로 락 획득/해제 불가. Router에서 503 + code REDIS_LOCK_UNAVAILABLE으로 변환."""

    pass


class BlocklistUnavailableError(Exception):
    """Blocklist(Redis) 회로 open 또는 일시 불가. 로그아웃 등에서 호출자가 재시도/503 응답 가능."""

    pass


def _redis_pool_kwargs() -> dict:
    """Redis ConnectionPool 공통 옵션. 타임아웃·디코드."""
    return {
        "decode_responses": True,
        "socket_timeout": getattr(settings, "redis_socket_timeout", 5.0),
        "socket_connect_timeout": getattr(settings, "redis_socket_connect_timeout", 2.0),
    }


def _redis_ssl_kwargs() -> dict:
    """rediss:// 사용 시 TLS 검증 옵션을 반환. 그렇지 않으면 빈 dict."""
    url = getattr(settings, "redis_url", None) or ""
    if not url.strip().startswith("rediss://"):
        return {}
    kwargs: dict = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    if getattr(settings, "redis_ca_certs", None):
        kwargs["ssl_ca_certs"] = settings.redis_ca_certs
    return kwargs


def create_blocklist_client() -> RedisAsyncio | None:
    """
    Blocklist용 비동기 Redis 클라이언트. max_connections·타임아웃 명시.
    redis_url 없으면 None. lifespan에서 한 번 생성해 app.state에 보관.
    """
    raw_url = getattr(settings, "redis_url", None) or ""
    redis_url = raw_url.strip()
    if not redis_url:
        return None
    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("redis.asyncio not available. Blocklist disabled.")
        return None
    pool = redis.ConnectionPool.from_url(
        redis_url,
        max_connections=settings.redis_blocklist_max_connections,
        **_redis_pool_kwargs(),
        **_redis_ssl_kwargs(),
    )
    return redis.Redis(connection_pool=pool)


def create_trigger_lock_client() -> RedisAsyncio | None:
    """
    Trigger 락 전용 비동기 Redis 클라이언트. Blocklist 풀과 분리해 인증 장애 전파 완화.
    단일 Redis 인스턴스는 SPOF이므로 풀 분리만으로는 완전 격리 아님(CAUTIONS 참고).
    """
    raw_url = getattr(settings, "redis_url", None) or ""
    redis_url = raw_url.strip()
    if not redis_url:
        return None
    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("redis.asyncio not available. Trigger lock disabled.")
        return None
    pool = redis.ConnectionPool.from_url(
        redis_url,
        max_connections=getattr(settings, "redis_trigger_lock_max_connections", 5),
        **_redis_pool_kwargs(),
        **_redis_ssl_kwargs(),
    )
    return redis.Redis(connection_pool=pool)


async def _add_access_to_blocklist_raw(
    client: RedisAsyncio | None, jti: str, ttl_seconds: int
) -> None:
    """Blocklist 추가(원시). Circuit Breaker에서 호출."""
    if client is None or ttl_seconds <= 0:
        return
    key = f"{BLOCKLIST_KEY_PREFIX}{jti}"
    await client.set(key, "1", ex=ttl_seconds)


class BlocklistCircuitBreaker:
    """Blocklist Redis 호출 래퍼. 연속 실패 시 열림(open) → Fail-open(서명만 검증 통과)."""

    def __init__(self) -> None:
        self._failures = 0
        self._open_until = 0.0
        self._state = "closed"  # closed | open | half_open
        self._lock = asyncio.Lock()

    async def _record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            if self._state == "half_open":
                self._state = "closed"

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= getattr(
                settings, "redis_blocklist_circuit_failure_threshold", 5
            ):
                self._state = "open"
                self._open_until = time.monotonic() + getattr(
                    settings, "redis_blocklist_circuit_open_seconds", 30.0
                )

    async def _maybe_try_half_open(self) -> bool:
        async with self._lock:
            if self._state == "open" and time.monotonic() >= self._open_until:
                self._state = "half_open"
                return True
            return self._state == "closed" or self._state == "half_open"

    def _is_open(self) -> bool:
        return self._state == "open"


_blocklist_circuit = BlocklistCircuitBreaker()


async def add_access_to_blocklist(
    client: RedisAsyncio | None, jti: str, ttl_seconds: int
) -> None:
    """Access Token jti를 Blocklist에 추가. Circuit Breaker 적용. 열림 시 BlocklistUnavailableError."""
    if client is None or ttl_seconds <= 0:
        return
    if not await _blocklist_circuit._maybe_try_half_open():
        raise BlocklistUnavailableError("Blocklist unavailable (circuit open)")
    try:
        await _add_access_to_blocklist_raw(client, jti, ttl_seconds)
        await _blocklist_circuit._record_success()
    except Exception as e:
        logger.warning("Blocklist add failed (jti=%s): %s", jti, e, exc_info=True)
        await _blocklist_circuit._record_failure()
        raise BlocklistUnavailableError("Blocklist temporarily unavailable") from e


async def acquire_trigger_lock(
    client: RedisAsyncio | None, college_code: str
) -> tuple[bool, str | None]:
    """
    college별 크롤 트리거 락 획득. SET key <uuid> NX EX.
    성공 시 (True, token), 이미 잠김 시 (False, None).
    Redis 인프라 오류 시 RedisLockUnavailableError 발생.
    client는 redis.asyncio.Redis. None이면 redis_trigger_lock_required=True 시 RedisLockUnavailableError, 아니면 (True, None).
    """
    if client is None:
        if getattr(settings, "redis_trigger_lock_required", False):
            raise RedisLockUnavailableError("Redis trigger lock required but client not configured")
        return (True, None)
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    token = str(uuid.uuid4())
    ttl = getattr(settings, "redis_trigger_lock_ttl_seconds", 2400)
    try:
        ok = await client.set(key, token, nx=True, ex=ttl)
        if ok:
            increment(LOCK_ACQUIRE_TOTAL)
        else:
            increment(LOCK_CONFLICT_TOTAL)
        return (bool(ok), token if ok else None)
    except Exception as e:
        logger.warning(
            "Trigger lock acquire failed (college=%s): %s", college_code, e, exc_info=True
        )
        raise RedisLockUnavailableError("Redis unavailable") from e


async def release_trigger_lock(
    client: RedisAsyncio | None, college_code: str, token: str
) -> bool:
    """
    락 해제(소유자만). Lua compare-and-del. client는 redis.asyncio.Redis.
    반환: True=삭제됨, False=소유자 아님 또는 이미 없음.
    """
    if client is None or not token:
        return False
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    try:
        n = await client.eval(LUA_RELEASE_IF_OWNER, 1, key, token)
        return n == 1
    except Exception as e:
        logger.warning(
            "Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True
        )
        return False


IDEMPOTENCY_VALUE_IN_PROGRESS = "in_progress"


def _idempotency_key_hash(idempotency_key: str) -> str:
    """Idempotency-Key 원문을 Redis 키용 짧은 해시로 변환. 키 길이·keyspace 오염 방지."""
    return hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]


def _idempotency_scope_hash(scope: str) -> str:
    """요청 스코프(route+college_code 등)를 짧은 안정적 해시로 변환. 키 길이 제한용."""
    return hashlib.sha256(scope.encode()).hexdigest()[:16]


async def try_claim_trigger_idempotency(
    client: RedisAsyncio | None, idempotency_key: str, scope: str
) -> bool:
    """
    Idempotency-Key 슬롯을 원자적으로 점유. SET key NX EX.
    scope(예: college_code 또는 "all")별로 별도 캐시. 동일 키라도 스코프가 다르면 다른 슬롯.
    성공 시 True(이번 요청이 처리 담당), 이미 존재 시 False(다른 요청이 점유 중 또는 완료).
    """
    if client is None or not idempotency_key:
        return True  # Redis 없으면 클레임 검사 생략, 기존처럼 진행
    scope_hash = _idempotency_scope_hash(scope)
    key = f"{TRIGGER_IDEMPOTENCY_KEY_PREFIX}{_idempotency_key_hash(idempotency_key)}:{scope_hash}"
    try:
        ok = await client.set(
            key,
            IDEMPOTENCY_VALUE_IN_PROGRESS,
            nx=True,
            ex=TRIGGER_IDEMPOTENCY_TTL_SECONDS,
        )
        return bool(ok)
    except Exception as e:
        # Redis 장애 시 idempotency는 비활성화하고, 실제 크롤 트리거는 진행되도록 허용한다.
        logger.warning(
            "Trigger idempotency claim failed (key=%s); proceeding without idempotency: %s",
            idempotency_key[:32],
            e,
        )
        return True


async def get_trigger_idempotency_result(
    client: RedisAsyncio | None, idempotency_key: str, scope: str
) -> dict | None:
    """동일 Idempotency-Key+scope로 이미 처리된 결과가 있으면 반환. 없으면 None. in_progress 값은 완료가 아니므로 None으로 취급하지 않고 별도 처리."""
    if client is None or not idempotency_key:
        return None
    scope_hash = _idempotency_scope_hash(scope)
    key = f"{TRIGGER_IDEMPOTENCY_KEY_PREFIX}{_idempotency_key_hash(idempotency_key)}:{scope_hash}"
    try:
        raw = await client.get(key)
        if raw is None:
            return None
        if raw == IDEMPOTENCY_VALUE_IN_PROGRESS:
            return {"status": "in_progress", "detail": "in_progress", "code": "IDEMPOTENCY_IN_PROGRESS"}
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Trigger idempotency get failed (key=%s): %s", idempotency_key[:32], e)
        return None


async def set_trigger_idempotency_result(
    client: RedisAsyncio | None, idempotency_key: str, scope: str, payload: dict
) -> None:
    """Idempotency-Key+scope에 결과 저장. TTL 24h. 재요청 시 202로 캐시된 결과 반환용."""
    if client is None or not idempotency_key:
        return
    scope_hash = _idempotency_scope_hash(scope)
    key = f"{TRIGGER_IDEMPOTENCY_KEY_PREFIX}{_idempotency_key_hash(idempotency_key)}:{scope_hash}"
    try:
        await client.set(
            key, json.dumps(payload), ex=TRIGGER_IDEMPOTENCY_TTL_SECONDS
        )
    except Exception as e:
        logger.warning("Trigger idempotency set failed (key=%s): %s", idempotency_key[:32], e)


_sync_redis_client = None


def _get_sync_redis_client():
    """heartbeat용 동기 Redis 클라이언트 싱글톤. 연결 churn 방지."""
    global _sync_redis_client
    if _sync_redis_client is None:
        import redis

        raw_url = getattr(settings, "redis_url", None) or ""
        if not raw_url.strip():
            return None
        url_stripped = raw_url.strip()
        ssl_kwargs = {}
        if url_stripped.startswith("rediss://"):
            ssl_kwargs = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
            if getattr(settings, "redis_ca_certs", None):
                ssl_kwargs["ssl_ca_certs"] = settings.redis_ca_certs
        socket_timeout = getattr(settings, "redis_socket_timeout", 5.0)
        socket_connect_timeout = getattr(settings, "redis_socket_connect_timeout", 2.0)
        _sync_redis_client = redis.Redis.from_url(
            url_stripped,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            **ssl_kwargs,
        )
    return _sync_redis_client


def renew_trigger_lock_sync(college_code: str, lock_token: str | None) -> bool:
    """
    단과대별 크롤 트리거 락 TTL 갱신(소유자만). 워커 장시간 실행/재시도 중 heartbeat용.
    동기 Redis 사용(Celery 워커 환경). 반환: True=갱신됨, False=소유자 아님/미갱신.
    """
    if not lock_token:
        return False
    from app.core.config import settings

    raw_url = getattr(settings, "redis_url", None) or ""
    if not raw_url.strip():
        return False
    ttl = getattr(settings, "redis_trigger_lock_ttl_seconds", 2400)
    client = _get_sync_redis_client()
    if client is None:
        return False
    try:
        key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
        n = client.eval(LUA_RENEW_IF_OWNER, 1, key, lock_token, ttl)
        return n == 1
    except Exception as e:
        logger.warning(
            "Trigger lock renew failed (college=%s): %s", college_code, e, exc_info=True
        )
        return False


def release_trigger_lock_sync(college_code: str, lock_token: str | None) -> None:
    """
    단과대별 크롤 트리거 락 해제(소유자만). 워커 완료/예외 시 호출.
    lock_token이 None이면 no-op(레거시 호출 방지). 동기 Redis 사용(Celery 워커 환경).
    싱글톤 클라이언트 재사용(커넥션 풀 유지).
    """
    if not lock_token:
        return
    from app.core.config import settings

    raw_url = getattr(settings, "redis_url", None) or ""
    if not raw_url.strip():
        return
    client = _get_sync_redis_client()
    if client is None:
        return
    try:
        key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
        client.eval(LUA_RELEASE_IF_OWNER, 1, key, lock_token)
    except Exception as e:
        logger.warning(
            "Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True
        )


async def _is_access_blocked_raw(
    client: RedisAsyncio | None, jti: str
) -> bool:
    """Blocklist 조회(원시). Circuit Breaker에서 호출."""
    if client is None:
        return False
    key = f"{BLOCKLIST_KEY_PREFIX}{jti}"
    exists = await client.exists(key)
    return bool(exists)


async def is_access_blocked(
    client: RedisAsyncio | None, jti: str, *, fail_closed: bool
) -> bool:
    """
    jti가 Blocklist에 있으면 True(무효). Circuit Breaker 적용.
    열림(open) 시 fail_closed=True면 True(인증 거부), False면 False.
    Redis 장애(예외) 시에도 fail_closed로 동일 결정.
    """
    if client is None:
        return False
    if not await _blocklist_circuit._maybe_try_half_open():
        return fail_closed
    try:
        result = await _is_access_blocked_raw(client, jti)
        await _blocklist_circuit._record_success()
        return result
    except Exception as e:
        logger.warning("Blocklist check failed (jti=%s): %s", jti, e, exc_info=True)
        await _blocklist_circuit._record_failure()
        return fail_closed
