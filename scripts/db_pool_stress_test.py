"""Async DB connection pool stress test (asyncio, SQLAlchemy 2 + psycopg).

Measures behavior under 100 concurrent sessions, pool exhaustion, and recovery
after pool invalidation or terminated PostgreSQL backends (optional). Hold wave
keeps the ORM session open with asyncio.sleep (not pg_sleep) so it runs on any DB.

Run from repo root (loads .env if python-dotenv is installed)::

    APP_ENTRY=migrate python scripts/db_pool_stress_test.py

Or with explicit pool overrides::

    APP_ENTRY=migrate python scripts/db_pool_stress_test.py --pool-size 4 --max-overflow 6

Dangerous: terminates other sessions on the same database for your DB user::

    APP_ENTRY=migrate python scripts/db_pool_stress_test.py --simulate-kill-backends

See docs/decisions/database-pool-capacity.md for capacity planning.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

os.environ.setdefault("APP_ENTRY", "migrate")

from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import POOL_PROFILE_R, _async_database_url, check_pool_budget


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _build_engine(
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: float,
    pool_recycle: int,
    pool_pre_ping: bool,
) -> AsyncEngine:
    raw = (settings.db.database_url or "").strip()
    if not raw:
        raise SystemExit("DATABASE_URL is not set. Configure .env or the environment.")

    connect_args: dict = {"options": f"-c statement_timeout={settings.db.db_statement_timeout_ms}"}
    kw: dict = {
        "pool_pre_ping": pool_pre_ping,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "connect_args": connect_args,
    }
    if pool_recycle >= 0:
        kw["pool_recycle"] = pool_recycle

    return create_async_engine(_async_database_url(raw), echo=False, **kw)


async def _short_query(session_maker: async_sessionmaker[AsyncSession], label: str) -> tuple[str, float, str | None]:
    t0 = time.perf_counter()
    err: str | None = None
    try:
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
    except SATimeoutError:
        err = "pool_timeout"
    except Exception as e:
        err = type(e).__name__ + ": " + str(e)[:200]
    dt = time.perf_counter() - t0
    return label, dt, err


async def _hold_query(
    session_maker: async_sessionmaker[AsyncSession],
    label: str,
    hold_sec: float,
) -> tuple[str, float, str | None]:
    """풀에서 연결을 hold_sec 동안 점유. DB별 pg_sleep 없이 asyncio.sleep으로 이식성 유지."""
    t0 = time.perf_counter()
    err: str | None = None
    try:
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
            await asyncio.sleep(hold_sec)
    except SATimeoutError:
        err = "pool_timeout"
    except Exception as e:
        err = type(e).__name__ + ": " + str(e)[:200]
    dt = time.perf_counter() - t0
    return label, dt, err


def _summarize_latencies(
    results: list[tuple[str, float, str | None]],
    title: str,
    *,
    engine: AsyncEngine | None = None,
    verbose_pool: bool = False,
) -> None:
    errors = [r for r in results if r[2]]
    oks = [r[1] for r in results if not r[2]]
    print(f"\n=== {title} ===")
    print(f"  total={len(results)} ok={len(oks)} errors={len(errors)}")
    if errors:
        kinds: dict[str, int] = {}
        for _, _, e in errors:
            key = (e or "unknown").split(":")[0]
            kinds[key] = kinds.get(key, 0) + 1
        print(f"  error breakdown: {kinds}")
    if oks:
        s = sorted(oks)
        print(
            f"  latency sec: min={min(s):.4f} p50={_percentile(s, 50):.4f} "
            f"p95={_percentile(s, 95):.4f} max={max(s):.4f}"
        )
    if verbose_pool and engine is not None:
        line = _pool_snapshot_line(engine)
        if line:
            print(line)


async def _run_wave(
    session_maker: async_sessionmaker[AsyncSession],
    concurrency: int,
    mode: str,
    hold_sec: float,
) -> list[tuple[str, float, str | None]]:
    if mode == "burst":
        tasks = [
            asyncio.create_task(_short_query(session_maker, f"b{i}"))
            for i in range(concurrency)
        ]
    else:
        tasks = [
            asyncio.create_task(_hold_query(session_maker, f"h{i}", hold_sec))
            for i in range(concurrency)
        ]
    return list(await asyncio.gather(*tasks))


async def _dispose_recovery_demo(engine: AsyncEngine, session_maker: async_sessionmaker[AsyncSession]) -> None:
    print("\n=== simulate: engine.dispose() then queries (fresh pool) ===")
    async with session_maker() as s:
        await s.execute(text("SELECT 1"))
    await engine.dispose()
    async with session_maker() as s:
        await s.execute(text("SELECT 1"))
    print("  dispose 후 SELECT 1 두 번 성공 (풀 재생성 경로 정상).")


async def _retry_after_dispose(
    engine: AsyncEngine,
    session_maker: async_sessionmaker[AsyncSession],
    retries: int,
    interval: float,
) -> None:
    """앱의 verify_db_connection과 유사: 풀 무효화 후 동일 세션 팩토리로 재시도."""
    print("\n=== simulate: retry loop after forced dispose (pre_ping + 새 연결) ===")
    await engine.dispose()
    last: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            async with session_maker() as s:
                await s.execute(text("SELECT 1"))
            print(f"  attempt {attempt}/{retries}: OK")
            return
        except BaseException as exc:
            last = exc
            print(f"  attempt {attempt}/{retries}: {type(exc).__name__}: {exc}")
            if attempt < retries:
                await asyncio.sleep(interval)
    raise RuntimeError(f"retry exhausted: {last}") from last


async def _simulate_kill_other_backends(database_url: str) -> int:
    """같은 DB·같은 역할의 다른 백엔드 세션을 종료 (풀에 있던 연결 포함)."""
    try:
        import psycopg
    except ImportError as e:
        raise SystemExit("psycopg is required for --simulate-kill-backends") from e

    dsn = _async_database_url(database_url)
    if "postgresql" not in dsn.lower():
        raise SystemExit("--simulate-kill-backends is only supported for PostgreSQL.")

    terminated = 0
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT pg_backend_pid()")
            my_pid = (await cur.fetchone())[0]
            await cur.execute(
                """
                SELECT pid FROM pg_stat_activity
                WHERE datname = current_database()
                  AND usename = current_user
                  AND pid <> %s
                  AND backend_type = 'client backend'
                """,
                (my_pid,),
            )
            pids = [row[0] for row in await cur.fetchall()]
        for pid in pids:
            async with conn.cursor() as cur2:
                await cur2.execute("SELECT pg_terminate_backend(%s)", (pid,))
                row = await cur2.fetchone()
                if row and row[0]:
                    terminated += 1
    return terminated


def _pool_snapshot_line(engine: AsyncEngine) -> str | None:
    try:
        pool = engine.sync_engine.pool
        checked_out = getattr(pool, "checkedout", None)
        checked_in = getattr(pool, "checkedin", None)
        size_fn = getattr(pool, "size", None)
        if not callable(checked_out) or not callable(size_fn):
            return None
        parts = [f"checked_out={checked_out()}", f"pool.size()={size_fn()}"]
        if callable(checked_in):
            parts.append(f"checked_in={checked_in()}")
        return "  [pool] " + ", ".join(parts)
    except Exception:
        return None


def _print_budget_hint(pool_size: int, max_overflow: int) -> None:
    eff = settings.db.db_max_connections
    res = check_pool_budget(eff)
    print("\n=== pool budget (current settings.db_*) ===")
    print(f"  {res.message}")
    p_async, o_async, _, _ = POOL_PROFILE_R
    print(
        f"  코드 참고 프로파일 R (async): pool_size={p_async}, max_overflow={o_async} "
        f"(POOL_PROFILE_R, 예산 검사에는 미사용)"
    )
    cap = pool_size + max_overflow
    print(
        f"  이번 실행 풀 상한(프로세스 1개): pool_size + max_overflow = {pool_size} + {max_overflow} = {cap}"
    )


def _recommendations(
    concurrency: int,
    burst_errors: int,
    saturated_errors: int,
    pool_size: int,
    max_overflow: int,
) -> None:
    cap = pool_size + max_overflow
    print("\n=== recommendations (운영 판단용 휴리스틱) ===")
    if burst_errors == 0:
        print(
            f"- burst: {concurrency}개 동시 짧은 쿼리는 현재 풀({cap} 연결 상한)과 pool_timeout으로 처리됨."
        )
    else:
        print(
            f"- burst: 타임아웃/오류 {burst_errors}건 → pool_timeout을 늘리거나, "
            "pool_size+max_overflow를 키우거나, 동시 DB 사용 구간을 줄이세요."
        )
    if saturated_errors > 0:
        print(
            f"- hold: 동시에 연결을 오래 잡는 작업이 {concurrency}개인데 풀 상한은 {cap}입니다. "
            f"장시간 점유 쿼리 기준 동시성은 대략 ≤ {cap} 이어야 합니다 (워커·프로세스당 풀 1개 가정)."
        )
        print(
            "  100개 워크로드가 모두 동시에 DB를 붙잡는다면, 단일 프로세스에서는 "
            "pool_size+max_overflow ≥ 100 이 필요하거나( DB max_connections 예산 확인 ), "
            "애플리케이션에서 세마포어/큐로 DB 동시 사용을 제한해야 합니다."
        )
    else:
        print(
            "- hold: 이번 hold 시간/동시성에서는 풀 고갈이 관측되지 않았습니다 "
            "(pool_timeout이 충분히 크거나 부하가 풀 용량 이하)."
        )
    print(
        "- 기본 가이드: 짧은 요청만 있다면 프로파일 R 근처(예: 4+6)로도 burst는 통과하는 경우가 많고, "
        "장기 쿼리·SSE·스트리밍 등 연결 장시간 점유가 있으면 그 피크만큼 풀을 키워야 합니다."
    )
    print(
        "- PostgreSQL max_connections·예산식은 docs/decisions/database-pool-capacity.md 및 DEPLOYMENT.md 참고."
    )


async def _amain(args: argparse.Namespace) -> int:
    pool_size = args.pool_size if args.pool_size is not None else settings.db.db_pool_size_async
    max_overflow = args.max_overflow if args.max_overflow is not None else settings.db.db_pool_max_overflow_async
    pool_timeout = args.pool_timeout if args.pool_timeout is not None else settings.db.db_pool_timeout_async
    pool_recycle = args.pool_recycle if args.pool_recycle is not None else settings.db.db_pool_recycle_async

    engine = _build_engine(
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=not args.no_pre_ping,
    )
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    vp = args.verbose_pool

    print(
        f"Engine: pool_size={pool_size} max_overflow={max_overflow} "
        f"pool_timeout={pool_timeout}s pool_pre_ping={not args.no_pre_ping} "
        f"pool_recycle={pool_recycle}"
    )
    _print_budget_hint(pool_size, max_overflow)

    exit_code = 0
    try:
        burst = await _run_wave(session_maker, args.concurrency, "burst", args.hold_sec)
        _summarize_latencies(
            burst,
            f"Burst: {args.concurrency} concurrent SELECT 1",
            engine=engine,
            verbose_pool=vp,
        )

        saturated = await _run_wave(session_maker, args.concurrency, "hold", args.hold_sec)
        _summarize_latencies(
            saturated,
            f"Hold: {args.concurrency} concurrent (session open + asyncio.sleep({args.hold_sec}s))",
            engine=engine,
            verbose_pool=vp,
        )

        burst_err = sum(1 for _, _, e in burst if e)
        sat_err = sum(1 for _, _, e in saturated if e)
        _recommendations(args.concurrency, burst_err, sat_err, pool_size, max_overflow)

        await _dispose_recovery_demo(engine, session_maker)

        retries = max(1, settings.db.db_connect_retries)
        interval = max(0.5, settings.db.db_connect_retry_interval_sec)
        await _retry_after_dispose(engine, session_maker, retries, interval)

        if args.simulate_kill_backends:
            raw = (settings.db.database_url or "").strip()
            print(
                "\n=== simulate: pg_terminate_backend on other sessions (same DB user) ===\n"
                "  WARNING: affects all other connections for this user/database (including other apps)."
            )
            n = await _simulate_kill_other_backends(raw)
            print(f"  terminated_other_sessions={n}")
            post = await _run_wave(session_maker, min(20, args.concurrency), "burst", args.hold_sec)
            _summarize_latencies(
                post,
                "Post-kill burst (subset)",
                engine=engine,
                verbose_pool=vp,
            )
            post_err = sum(1 for _, _, e in post if e)
            if post_err == 0:
                print(
                    "  해석: 끊긴 연결은 pool_pre_ping(및 재연결)로 대체 가능한 경로로 보입니다."
                )
            else:
                print("  일부 오류 발생: 로그의 error breakdown을 확인하세요.")
            if args.strict and post_err:
                exit_code = 1

        if args.strict and (burst_err or sat_err):
            exit_code = 1
    finally:
        await engine.dispose()

    return exit_code


def main() -> None:
    p = argparse.ArgumentParser(description="DB async pool stress / recovery checks.")
    p.add_argument("--concurrency", type=int, default=100, help="Concurrent tasks (default 100).")
    p.add_argument(
        "--hold-sec",
        type=float,
        default=0.5,
        help="Seconds to keep each session open (asyncio.sleep) during hold wave.",
    )
    p.add_argument("--pool-size", type=int, default=None, help="Override pool_size (default: settings).")
    p.add_argument("--max-overflow", type=int, default=None, help="Override max_overflow (default: settings).")
    p.add_argument("--pool-timeout", type=float, default=None, help="Override pool_timeout seconds.")
    p.add_argument("--pool-recycle", type=int, default=None, help="Override pool_recycle (-1 to disable).")
    p.add_argument(
        "--no-pre-ping",
        action="store_true",
        help="Disable pool_pre_ping (not recommended; for comparison only).",
    )
    p.add_argument(
        "--simulate-kill-backends",
        action="store_true",
        help="Terminate other PostgreSQL client backends for this DB user (dangerous).",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if burst/hold/post-kill wave has any errors (for CI).",
    )
    p.add_argument(
        "--verbose-pool",
        action="store_true",
        help="After each wave, print SQLAlchemy pool checked_out/size snapshot when available.",
    )
    args = p.parse_args()
    code = asyncio.run(_amain(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
