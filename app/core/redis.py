"""Redis 비동기 클라이언트. Blocklist(Access Token 무효화)용. 풀 크기 명시로 동시 처리량 대응."""

import asyncio
import hashlib
import json
import logging
import ssl
import time
import uuid
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis as RedisAsyncio

from app.core.config import settings
from app.core.exceptions import RedisInfraError
from app.core.metrics import (
    LOCK_ACQUIRE_TOTAL,
    LOCK_CONFLICT_TOTAL,
    increment,
)

logger = logging.getLogger(__name__)


def _jti_log_safe(jti: object) -> str:
    """jti를 로그에 남기지 않기 위해 해시 앞 8자만 반환. 추적용으로만 사용."""
    raw = str(jti).strip() if jti is not None else ""
    if not raw:
        return "n/a"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


BLOCKLIST_KEY_PREFIX = "dicee:blocklist:access:"
TRIGGER_IDEMPOTENCY_KEY_PREFIX = "dicee:trigger_idempotency:"
TRIGGER_IDEMPOTENCY_TTL_SECONDS = 86400  # 24h
CRAWL_TASK_EXECUTION_CLAIM_KEY_PREFIX = "dicee:crawl_task_execution:"

# --- Cache Stampede 방어용 Lock Prefix 추가 ---
CACHE_LOCK_KEY_PREFIX = "dicee:cache_lock:"

# 단과대별 크롤 트리거 분산락. TTL 내 중복 enqueue 방지. 워커 완료 시 조기 해제.
# 좀비 락 복구: 워커 하드 킬/파티션 시 TTL 만료로만 해제. Compare-and-del은 정상 종료 시 타인 락 삭제 방지용.
TRIGGER_LOCK_KEY_PREFIX = "dicee:trigger_lock:"
# TTL은 config.redis_trigger_lock_ttl_seconds 사용. 기본 2400 (max_countdown + safety_margin).

# 마지막 크롤 성공 시각(필드=college_code, 값=UTC ISO). 워커 HSET, /ready 진단용 HGETALL.
LAST_CRAWL_SUCCESS_HASH_KEY = "dicee:last_crawl_success"
# 4단계→5단계 알림·매칭 스텁 큐(RPUSH + LTRIM 상한). Redis 실패 시 AI 태스크는 성공 유지(fail-open).
AI_EXTRACTION_COMPLETED_QUEUE_KEY = "dicee:ai_extraction_completed_queue"
AI_EXTRACTION_COMPLETED_QUEUE_MAX = 1000

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


class RedisLockUnavailableError(RedisInfraError):
    """Redis 인프라 오류로 락 획득/해제 불가. 전역 핸들러에서 503 + code REDIS_LOCK_UNAVAILABLE으로 변환."""

    pass


class RedisIdempotencyUnavailableError(RedisInfraError):
    """Redis infra error: idempotency claim unavailable.

    Mapped to HTTP 503 with code REDIS_IDEMPOTENCY_UNAVAILABLE.
    """

    pass


class BlocklistUnavailableError(Exception):
    """Blocklist(Redis) 회로 open 또는 일시 불가. 로그아웃 등에서 호출자가 재시도/503 응답 가능."""

    pass


def _redis_pool_kwargs() -> dict:
    """Redis ConnectionPool 공통 옵션. 타임아웃·디코드."""
    return {
        "decode_responses": True,
        "socket_timeout": settings.redis.redis_socket_timeout,
        "socket_connect_timeout": settings.redis.redis_socket_connect_timeout,
    }


def _redis_ssl_kwargs() -> dict:
    """rediss:// 사용 시 TLS 검증 옵션을 반환. 그렇지 않으면 빈 dict."""
    url = (settings.redis.redis_url or "").strip()
    if not url.strip().startswith("rediss://"):
        return {}
    kwargs: dict = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    if settings.redis.redis_ca_certs:
        kwargs["ssl_ca_certs"] = settings.redis.redis_ca_certs
    return kwargs


def create_blocklist_client() -> RedisAsyncio | None:
    """
    Blocklist용 비동기 Redis 클라이언트. max_connections·타임아웃 명시.
    redis_url 없으면 None. lifespan에서 한 번 생성해 app.state에 보관.
    """
    redis_url = (settings.redis.redis_url or "").strip()
    if not redis_url:
        return None
    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("redis.asyncio not available. Blocklist disabled.")
        return None
    pool = redis.ConnectionPool.from_url(
        redis_url,
        max_connections=settings.redis.redis_blocklist_max_connections,
        **_redis_pool_kwargs(),
        **_redis_ssl_kwargs(),
    )
    return redis.Redis(connection_pool=pool)


def create_trigger_lock_client() -> RedisAsyncio | None:
    """
    Trigger 락 전용 비동기 Redis 클라이언트. Blocklist 풀과 분리해 인증 장애 전파 완화.
    단일 Redis 인스턴스는 SPOF이므로 풀 분리만으로는 완전 격리 아님(CAUTIONS 참고).
    """
    redis_url = (settings.redis.redis_url or "").strip()
    if not redis_url:
        return None
    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("redis.asyncio not available. Trigger lock disabled.")
        return None
    pool = redis.ConnectionPool.from_url(
        redis_url,
        max_connections=settings.redis.redis_trigger_lock_max_connections,
        **_redis_pool_kwargs(),
        **_redis_ssl_kwargs(),
    )
    return redis.Redis(connection_pool=pool)


async def _add_access_to_blocklist_raw(client: RedisAsyncio | None, jti: str, ttl_seconds: int) -> None:
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
            was_half_open = self._state == "half_open"
            self._failures += 1
            if self._failures >= settings.redis.redis_blocklist_circuit_failure_threshold:
                self._state = "open"
                # half_open에서 실패한 뒤에는 더 짧은 대기(half_open_interval)로 재시도 허용
                if was_half_open:
                    self._open_until = (
                        time.monotonic() + settings.redis.redis_blocklist_circuit_half_open_interval_seconds
                    )
                else:
                    self._open_until = time.monotonic() + settings.redis.redis_blocklist_circuit_open_seconds

    async def _maybe_try_half_open(self) -> bool:
        async with self._lock:
            if self._state == "open" and time.monotonic() >= self._open_until:
                self._state = "half_open"
                return True
            return self._state == "closed" or self._state == "half_open"

    def _is_open(self) -> bool:
        return self._state == "open"


_blocklist_circuit = BlocklistCircuitBreaker()


async def add_access_to_blocklist(client: RedisAsyncio | None, jti: str, ttl_seconds: int) -> None:
    """Access Token jti를 Blocklist에 추가. Circuit Breaker 적용. 열림 시 BlocklistUnavailableError."""
    if client is None or ttl_seconds <= 0:
        return
    if not await _blocklist_circuit._maybe_try_half_open():
        raise BlocklistUnavailableError("Blocklist unavailable (circuit open)")
    try:
        await _add_access_to_blocklist_raw(client, jti, ttl_seconds)
        await _blocklist_circuit._record_success()
    except Exception as e:
        logger.warning(
            "Blocklist add failed (jti_hash=%s): %s",
            _jti_log_safe(jti),
            e,
            exc_info=True,
        )
        await _blocklist_circuit._record_failure()
        raise BlocklistUnavailableError("Blocklist temporarily unavailable") from e


async def acquire_trigger_lock(client: RedisAsyncio | None, college_code: str) -> tuple[bool, str | None]:
    """
    college별 크롤 트리거 락 획득. SET key <uuid> NX EX.
    성공 시 (True, token), 이미 잠김 시 (False, None).
    Redis 인프라 오류 시 RedisLockUnavailableError 발생.
    client는 redis.asyncio.Redis. None이면 redis_trigger_lock_required=True 시 에러, 아니면 (True, None).
    """
    if client is None:
        if settings.redis.redis_trigger_lock_required:
            raise RedisLockUnavailableError("Redis trigger lock required but client not configured")
        return (True, None)
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    token = str(uuid.uuid4())
    ttl = settings.redis.redis_trigger_lock_ttl_seconds
    try:
        ok = await client.set(key, token, nx=True, ex=ttl)
        if ok:
            increment(LOCK_ACQUIRE_TOTAL)
        else:
            increment(LOCK_CONFLICT_TOTAL)
        return (bool(ok), token if ok else None)
    except Exception as e:
        logger.warning("Trigger lock acquire failed (college=%s): %s", college_code, e, exc_info=True)
        raise RedisLockUnavailableError("Redis unavailable") from e


async def release_trigger_lock(client: RedisAsyncio | None, college_code: str, token: str) -> bool:
    """
    락 해제(소유자만). Lua compare-and-del. client는 redis.asyncio.Redis.
    반환: True=삭제됨, False=소유자 아님 또는 이미 없음.
    """
    if client is None or not token:
        return False
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    try:
        raw = await cast(Awaitable[Any], client.eval(LUA_RELEASE_IF_OWNER, 1, key, token))
        return bool(raw == 1)
    except Exception as e:
        logger.warning("Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True)
        return False


IDEMPOTENCY_VALUE_IN_PROGRESS = "in_progress"


def _idempotency_key_hash(idempotency_key: str) -> str:
    """Idempotency-Key 원문을 Redis 키용 짧은 해시로 변환. 키 길이·keyspace 오염 방지."""
    return hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]


def _idempotency_scope_hash(scope: str) -> str:
    """요청 스코프(route+college_code 등)를 짧은 안정적 해시로 변환. 키 길이 제한용."""
    return hashlib.sha256(scope.encode()).hexdigest()[:16]


async def try_claim_trigger_idempotency(
    client: RedisAsyncio | None,
    idempotency_key: str,
    scope: str,
    *,
    fail_closed: bool = False,
) -> bool:
    """
    Idempotency-Key 슬롯을 원자적으로 점유. SET key NX EX.
    scope(예: college_code 또는 "all")별로 별도 캐시. 동일 키라도 스코프가 다르면 다른 슬롯.
    성공 시 True(이번 요청이 처리 담당), 이미 존재 시 False(다른 요청이 점유 중 또는 완료).
    fail_closed=True이면 Redis 예외 시 False 대신 RedisIdempotencyUnavailableError 발생(503 권장).
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
        if fail_closed:
            raise RedisIdempotencyUnavailableError("Trigger idempotency claim failed.") from e
        logger.warning(
            "Trigger idempotency claim failed; proceeding without idempotency.",
            exc_info=True,
        )
        return True


async def get_trigger_idempotency_result(client: RedisAsyncio | None, idempotency_key: str, scope: str) -> dict | None:
    """동일 Idempotency-Key+scope로 이미 처리된 결과가 있으면 반환. 없으면 None.
    in_progress 값은 완료가 아니므로 별도 처리."""
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
        return cast(dict[str, Any], json.loads(raw))
    except (json.JSONDecodeError, Exception):
        logger.warning("Trigger idempotency get failed.", exc_info=True)
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
        await client.set(key, json.dumps(payload), ex=TRIGGER_IDEMPOTENCY_TTL_SECONDS)
    except Exception:
        logger.warning("Trigger idempotency set failed.", exc_info=True)


async def clear_trigger_idempotency_in_progress(
    client: RedisAsyncio | None,
    idempotency_key: str,
    scope: str,
) -> bool:
    """
    Idempotency-Key+scope의 in_progress 클레임만 삭제한다.
    이미 결과 payload가 저장된 경우에는 삭제하지 않는다.
    """
    if client is None or not idempotency_key:
        return False
    scope_hash = _idempotency_scope_hash(scope)
    key = f"{TRIGGER_IDEMPOTENCY_KEY_PREFIX}{_idempotency_key_hash(idempotency_key)}:{scope_hash}"
    try:
        raw = await cast(
            Awaitable[Any],
            client.eval(LUA_RELEASE_IF_OWNER, 1, key, IDEMPOTENCY_VALUE_IN_PROGRESS),
        )
        return bool(raw == 1)
    except Exception:
        logger.warning("Trigger idempotency clear failed.", exc_info=True)
        return False


# renew_trigger_lock_sync·release_trigger_lock_sync 모두 이 싱글톤 사용. 호출마다 from_url/close 금지.
_sync_redis_client = None


def _get_sync_redis_client():
    """heartbeat·락 해제용 동기 Redis 클라이언트 싱글톤. 연결 churn 방지."""
    global _sync_redis_client
    if _sync_redis_client is None:
        import redis

        url_stripped = (settings.redis.redis_url or "").strip()
        if not url_stripped:
            return None
        ssl_kwargs: dict[str, Any] = {}
        if url_stripped.startswith("rediss://"):
            ssl_kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
            if settings.redis.redis_ca_certs:
                ssl_kwargs["ssl_ca_certs"] = settings.redis.redis_ca_certs
        socket_timeout = settings.redis.redis_socket_timeout
        socket_connect_timeout = settings.redis.redis_socket_connect_timeout
        _sync_redis_client = redis.Redis.from_url(
            url_stripped,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            **ssl_kwargs,
        )
    return _sync_redis_client


def get_shared_sync_redis_client():
    """Shared sync Redis client singleton for worker-side sync paths."""
    return _get_sync_redis_client()


def renew_trigger_lock_sync(college_code: str, lock_token: str | None) -> bool:
    """
    단과대별 크롤 트리거 락 TTL 갱신(소유자만). 워커 장시간 실행/재시도 중 heartbeat용.
    동기 Redis 사용(Celery 워커 환경). 반환: True=갱신됨, False=소유자 아님/미갱신.
    """
    if not lock_token:
        return False
    from app.core.config import settings

    if not (settings.redis.redis_url or "").strip():
        return False
    ttl = settings.redis.redis_trigger_lock_ttl_seconds
    client = _get_sync_redis_client()
    if client is None:
        return False
    try:
        key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
        # Redis eval ARGV는 문자열 기반이므로 TTL을 str로 캐스팅해 전달한다.
        n = client.eval(LUA_RENEW_IF_OWNER, 1, key, lock_token, str(ttl))
        return bool(n == 1)
    except Exception as e:
        logger.warning("Trigger lock renew failed (college=%s): %s", college_code, e, exc_info=True)
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

    if not (settings.redis.redis_url or "").strip():
        return
    client = _get_sync_redis_client()
    if client is None:
        return
    try:
        key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
        client.eval(LUA_RELEASE_IF_OWNER, 1, key, lock_token)
    except Exception as e:
        logger.warning("Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True)


def record_last_crawl_success_sync(college_code: str) -> None:
    """단과대별 마지막 크롤 성공 시각을 Redis HASH에 기록. Redis 오류 시 fail-open."""
    code = (college_code or "").strip()
    if not code:
        return
    client = _get_sync_redis_client()
    if client is None:
        return
    from datetime import UTC, datetime

    ts = datetime.now(UTC).replace(microsecond=0).isoformat()
    try:
        client.hset(LAST_CRAWL_SUCCESS_HASH_KEY, code, ts)
    except Exception as e:
        logger.warning(
            "last_crawl_success record failed (college=%s): %s",
            code,
            e,
            exc_info=True,
        )


def push_ai_extraction_completed_stub_sync(notice_id: str, college_code: str) -> None:
    """
    매칭·푸시 소비자(5~6단계)용 스텁 리스트. Redis 장애 시 로그만 남기고 예외를 밖으로 내지 않음.
    """
    nid = (notice_id or "").strip()
    if not nid:
        return
    client = _get_sync_redis_client()
    if client is None:
        return
    from datetime import UTC, datetime

    payload = json.dumps(
        {
            "notice_id": nid,
            "college_code": college_code or "unknown",
            "ts": datetime.now(UTC).replace(microsecond=0).isoformat(),
        },
        separators=(",", ":"),
    )
    try:
        client.rpush(AI_EXTRACTION_COMPLETED_QUEUE_KEY, payload)
        client.ltrim(
            AI_EXTRACTION_COMPLETED_QUEUE_KEY,
            -AI_EXTRACTION_COMPLETED_QUEUE_MAX,
            -1,
        )
    except Exception as e:
        logger.warning(
            "ai_extraction_completed queue push failed (notice_id=%s): %s",
            nid,
            e,
            exc_info=True,
        )


def claim_crawl_task_execution(task_id: str) -> bool:
    """
    Celery task delivery 중복 실행 방지를 위한 실행 클레임(SET NX, 짧은 TTL).
    워커 생존 중에는 renew_crawl_task_execution_claim으로 TTL 연장.
    Redis 미구성/일시 장애 시 fail-open으로 True를 반환한다.
    """
    if not task_id:
        return True
    from app.core.config import settings

    if not (settings.redis.redis_url or "").strip():
        return True
    client = _get_sync_redis_client()
    if client is None:
        return True
    key = f"{CRAWL_TASK_EXECUTION_CLAIM_KEY_PREFIX}{task_id}"
    ttl = int(settings.crawl_task_execution_claim_ttl_seconds)
    try:
        ok = client.set(
            key,
            "1",
            nx=True,
            ex=ttl,
        )
        return bool(ok)
    except Exception as e:
        logger.warning("Task execution claim failed (task_id=%s): %s", task_id, e, exc_info=True)
        return True


def renew_crawl_task_execution_claim(task_id: str) -> bool:
    """
    실행 클레임 키 TTL 연장(EXPIRE). 워커 하트비트에서만 호출.
    프로세스가 죽으면 갱신이 멈춰 키가 만료되고, 브로커 재전달 시 SET NX가 성공할 수 있다.
    반환: True=키 존재하며 TTL 갱신됨, False=키 없음 또는 Redis 오류.
    """
    if not task_id:
        return False
    from app.core.config import settings

    if not (settings.redis.redis_url or "").strip():
        return True
    client = _get_sync_redis_client()
    if client is None:
        return False
    key = f"{CRAWL_TASK_EXECUTION_CLAIM_KEY_PREFIX}{task_id}"
    ttl = int(settings.crawl_task_execution_claim_ttl_seconds)
    try:
        return bool(client.expire(key, ttl))
    except Exception as e:
        logger.warning(
            "Task execution claim renew failed (task_id=%s): %s",
            task_id,
            e,
            exc_info=True,
        )
        return False


def release_crawl_task_execution(task_id: str) -> None:
    """claim_crawl_task_execution으로 획득한 실행 클레임을 해제한다."""
    if not task_id:
        return
    from app.core.config import settings

    if not (settings.redis.redis_url or "").strip():
        return
    client = _get_sync_redis_client()
    if client is None:
        return
    key = f"{CRAWL_TASK_EXECUTION_CLAIM_KEY_PREFIX}{task_id}"
    try:
        client.delete(key)
    except Exception as e:
        logger.warning("Task execution release failed (task_id=%s): %s", task_id, e, exc_info=True)


async def _is_access_blocked_raw(client: RedisAsyncio | None, jti: str) -> bool:
    """Blocklist 조회(원시). Circuit Breaker에서 호출."""
    if client is None:
        return False
    key = f"{BLOCKLIST_KEY_PREFIX}{jti}"
    exists = await client.exists(key)
    return bool(exists)


async def is_access_blocked(client: RedisAsyncio | None, jti: str, *, fail_closed: bool) -> bool:
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
        logger.warning(
            "Blocklist check failed (jti_hash=%s): %s",
            _jti_log_safe(jti),
            e,
            exc_info=True,
        )
        await _blocklist_circuit._record_failure()
        return fail_closed


# ==============================================================================
# Cache Stampede 방어막: Soft TTL + Mutex Lock 로직
# ==============================================================================


async def set_cache_with_soft_ttl(
    client: RedisAsyncio | None,
    key: str,
    data: Any,
    soft_ttl_seconds: int,
    hard_ttl_seconds: int,
) -> None:
    """
    Soft TTL이 포함된 캐시를 저장합니다.
    실제 데이터와 논리적 만료 시간(soft_ttl)을 함께 JSON으로 묶어 저장합니다.
    hard_ttl_seconds는 메모리 누수를 막기 위한 최후의 물리적 만료 시간입니다 (soft_ttl보다 넉넉해야 함).
    갱신에 성공한 호출자는 release_cache_lock(client, key, token)를 호출해 락을 조기 해제할 수 있습니다.
    """
    if client is None:
        return
    payload = {"data": data, "soft_ttl": time.time() + soft_ttl_seconds}
    try:
        await client.set(key, json.dumps(payload), ex=hard_ttl_seconds)
    except Exception as e:
        logger.warning("Cache set_with_soft_ttl failed (key=%s): %s", key, e)


async def release_cache_lock(client: RedisAsyncio | None, key: str, token: str) -> bool:
    """
    Soft TTL 캐시 갱신 후 보유 중인 락을 조기 삭제합니다.
    lock value가 token과 일치할 때만 삭제(compare-and-del, Lua). 타인 락 삭제 방지.
    get_cache_with_soft_ttl로 획득한 lock_token을 전달해야 합니다.
    반환: True=삭제됨, False=소유자 아님·키 없음·client/token 없음·Redis 예외.
    """
    if client is None or not token:
        return False
    lock_key = f"{CACHE_LOCK_KEY_PREFIX}{key}"
    try:
        raw = await cast(Awaitable[Any], client.eval(LUA_RELEASE_IF_OWNER, 1, lock_key, token))
        return bool(raw == 1)
    except Exception as e:
        logger.warning("Cache lock release failed (key=%s): %s", key, e)
        return False


async def get_cache_with_soft_ttl(
    client: RedisAsyncio | None, key: str, lock_ttl_seconds: int = 10
) -> tuple[Any | None, bool, str | None]:
    """
    Soft TTL 캐시 조회 및 Mutex Lock 획득 (Cache Stampede 방어).
    락 값은 UUID token으로 저장. 갱신 후 release_cache_lock(client, key, token)로 compare-and-del.

    반환값: (캐시된 데이터, should_refresh, lock_token)
    - (data, False, None): 신선한 캐시 또는 stale이지만 락 미획득 → 즉시 반환
    - (data, True, token): stale이고 락 획득 → DB 갱신 후 set + release_cache_lock(key, token)
    - (None, True, token): Hard Miss, 락 획득 → DB 조회 후 set
    - (None, False, None): Hard Miss, 락 미획득 → wait 후 재조회
    """
    if client is None:
        return None, True, None

    try:
        raw = await client.get(key)
        lock_key = f"{CACHE_LOCK_KEY_PREFIX}{key}"

        if not raw:
            token = str(uuid.uuid4())
            acquired = await client.set(lock_key, token, nx=True, ex=lock_ttl_seconds)
            return None, bool(acquired), token if acquired else None

        payload = json.loads(raw)
        data = payload.get("data")
        soft_ttl = payload.get("soft_ttl", 0)

        if time.time() > soft_ttl:
            token = str(uuid.uuid4())
            acquired = await client.set(lock_key, token, nx=True, ex=lock_ttl_seconds)
            if acquired:
                return data, True, token
            return data, False, None

        return data, False, None

    except Exception as e:
        logger.warning("Cache get_with_soft_ttl failed (key=%s): %s", key, e)
        return None, True, None
