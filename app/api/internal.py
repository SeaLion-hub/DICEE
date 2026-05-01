"""
내부 전용 API (Cron·관리). 보안 키는 Header만 허용(X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
Query 파라미터 시크릿 미지원(Access Log 유출 방지). college별 분산락으로 중복 enqueue 방지.
"""

# ruff: noqa: E501

import logging
from dataclasses import asdict, is_dataclass
from html import escape
from typing import cast
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.api_rate_limit import (
    RateLimitUnavailableError,
    check_rate_limit,
)
from app.core.config import settings
from app.core.crawler_config import college_codes_for_openapi
from app.core.database import read_only_session_cm
from app.core.deps import (
    ReadOnlySessionDep,
    SessionDep,
    get_ai_admin_service,
    get_crawl_stats_service,
    get_internal_crawl_service,
    get_notice_preview_service,
    get_redis_trigger_lock,
)
from app.core.internal_auth import (
    CrawlTriggerNotConfiguredError,
    InvalidCrawlTriggerSecretError,
    check_crawl_trigger_secret,
)
from app.core.ip_hmac import compute_ip_hmac
from app.core.network import get_client_ip
from app.core.read_cache import (
    get_cached_with_soft_ttl,
    release_cached_lock,
    set_cached_with_soft_ttl,
    wait_for_cached,
)
from app.domain.contracts.internal_contracts import (
    TriggerCrawlCmd,
    TriggerCrawlResult,
    TriggerCrawlResultKind,
)
from app.schemas.internal import CrawlRunStatsItem, CrawlSourceFreshnessStatsItem, CrawlStatsResponse
from app.services.ai_admin_service import (
    AiAdminConflictError,
    AiAdminDependencyUnavailableError,
    AiAdminError,
    AiAdminNotFoundError,
    AiAdminService,
    AiAdminValidationError,
    payload_to_json,
    result_to_payload,
)
from app.services.crawl_stats_service import CrawlStatsService
from app.services.internal_crawl_service import InternalCrawlService, normalize_trigger_idempotency_key
from app.services.notice_preview_service import NoticePreviewRow, NoticePreviewService

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_AFTER_SECONDS = 60


def _render_preview_cell(items: list[str], *, empty_text: str = "-") -> str:
    if not items:
        return f"<span>{escape(empty_text)}</span>"
    lis = "".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<ul>{lis}</ul>"


def _render_engineering_preview_html(rows: list[NoticePreviewRow], *, limit: int) -> str:
    body_rows = []
    for row in rows:
        title_html = escape(row.title or "(제목 없음)")
        url_html = (
            f'<a href="{escape(row.url)}" target="_blank" rel="noopener noreferrer">원문 링크</a>' if row.url else "-"
        )
        body_rows.append(
            "<tr>"
            f"<td>{title_html}</td>"
            f"<td>{escape(row.published_at or '-')}</td>"
            f"<td>{url_html}</td>"
            f"<td>{_render_preview_cell([row.content_url], empty_text='-')}</td>"
            f"<td>{_render_preview_cell(row.image_urls)}</td>"
            f"<td>{_render_preview_cell(row.attachment_names)}</td>"
            f"<td>{_render_preview_cell(row.eligibility)}</td>"
            f"<td>{_render_preview_cell(row.dates)}</td>"
            f"<td>{_render_preview_cell(row.main_categories)}</td>"
            f"<td>{_render_preview_cell(row.sub_categories)}</td>"
            "</tr>"
        )
    rows_html = "".join(body_rows) or (
        "<tr><td colspan='10'>데이터가 없습니다. 공대 크롤링/AI 처리 후 다시 확인해 주세요.</td></tr>"
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Engineering Crawl Preview</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    h1 {{ margin: 0 0 8px 0; }}
    p.meta {{ color: #666; margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; word-break: break-word; }}
    th {{ background: #f4f4f4; }}
    ul {{ margin: 0; padding-left: 18px; }}
  </style>
</head>
<body>
  <h1>공대 크롤링/AI 임시 검수 페이지</h1>
  <p class="meta">college=engineering, latest={len(rows)} / limit={limit}</p>
  <table>
    <thead>
      <tr>
        <th>제목</th>
        <th>게시일</th>
        <th>원문</th>
        <th>본문 URL</th>
        <th>이미지</th>
        <th>첨부파일</th>
        <th>지원자격</th>
        <th>날짜</th>
        <th>대분류</th>
        <th>소분류</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""


def _json_pretty(value: object) -> str:
    return escape(payload_to_json(cast(dict[str, object], value) if isinstance(value, dict) else {"value": value}))


def _to_plain(value: object) -> dict[str, object]:
    if is_dataclass(value):
        return cast(dict[str, object], asdict(value))
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    raw = getattr(value, "__dict__", None)
    if isinstance(raw, dict):
        return cast(dict[str, object], raw)
    return {}


def _to_plain_list(values: list[object]) -> list[dict[str, object]]:
    return [_to_plain(value) for value in values]


def _format_cost(cost: dict[str, object]) -> str:
    total = cost.get("total_usd")
    if total is None:
        return "unknown"
    try:
        return f"${float(total):.8f}"
    except (TypeError, ValueError):
        return "unknown"


def _format_number(value: object) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


async def _admin_form_data(request: Request) -> dict[str, str]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in content_type:
        body = (await request.body()).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: values[-1] if values else "" for k, values in parsed.items()}
    if "application/json" in content_type:
        payload = await request.json()
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items()}
    return {}


def _form_bool(data: dict[str, str], key: str) -> bool:
    return (data.get(key) or "").strip().lower() in {"1", "true", "on", "yes"}


def _render_ai_admin_html(
    *,
    notices: list[dict[str, object]],
    dashboard: dict[str, object],
    result: dict[str, object] | None = None,
    message: str | None = None,
) -> str:
    options = []
    for notice in notices:
        nid = str(notice.get("id") or "")
        title = str(notice.get("title") or "(제목 없음)")
        college = str(notice.get("college_code") or "-")
        tokens = notice.get("total_tokens")
        label = f"[{college}] {title}"
        if tokens is not None:
            label += f" ({tokens} tokens)"
        options.append(f'<option value="{escape(nid)}">{escape(label)}</option>')
    options_html = "".join(options)

    result_html = """
        <div class="empty-state">
          <span class="empty-kicker">Ready</span>
          <h3>아직 실행 결과가 없습니다</h3>
          <p>최근 공지를 선택하고 드라이런을 실행하면 토큰 사용량, 예상 비용, 추출 요약이 여기에 표시됩니다.</p>
        </div>
        """
    if result is not None:
        usage = cast(dict[str, object], result.get("usage") or {})
        cost = cast(dict[str, object], result.get("cost") or {})
        meta = cast(dict[str, object], result.get("meta") or {})
        summary = cast(dict[str, object], result.get("summary") or {})
        notice_id = escape(str(result.get("notice_id") or ""))
        html_source = str(result.get("html_source") or "unknown")
        source_quality = str(result.get("source_quality") or "warning")
        usage_quality = str(result.get("usage_quality") or "unknown")
        cost_quality = str(result.get("cost_quality") or cost.get("reason") or "estimated")
        token_band = str(result.get("token_band") or "unknown")
        admin_advice = str(result.get("admin_advice") or "")
        result_html = f"""
        <div class="metric-grid result-metrics">
          <div class="metric-card">
            <span class="metric-label">Total Tokens</span>
            <strong>{escape(_format_number(usage.get("total_tokens")))}</strong>
            <small>band {escape(token_band)}</small>
          </div>
          <div class="metric-card">
            <span class="metric-label">Prompt Tokens</span>
            <strong>{escape(_format_number(usage.get("prompt_tokens")))}</strong>
            <small>model input</small>
          </div>
          <div class="metric-card">
            <span class="metric-label">Completion Tokens</span>
            <strong>{escape(_format_number(usage.get("completion_tokens")))}</strong>
            <small>model output</small>
          </div>
          <div class="metric-card">
            <span class="metric-label">Estimated Cost</span>
            <strong>{escape(_format_cost(cost))}</strong>
            <small>{escape(cost_quality)}</small>
          </div>
          <div class="metric-card">
            <span class="metric-label">Source Quality</span>
            <strong>{escape(source_quality)}</strong>
            <small>{escape(html_source)} · raw {escape(_format_number(meta.get("html_raw_len")))} chars</small>
          </div>
          <div class="metric-card">
            <span class="metric-label">Usage Quality</span>
            <strong>{escape(usage_quality)}</strong>
            <small>{escape(str(meta.get("model") or "model unknown"))} · {escape(str(meta.get("elapsed_ms") or 0))}ms</small>
          </div>
          <div class="metric-card">
            <span class="metric-label">Run Meta</span>
            <strong>{escape(str(meta.get("elapsed_ms") or 0))}ms</strong>
            <small>{escape(str(meta.get("model") or "model unknown"))} · vision {escape(str(meta.get("vision_used") or False))}</small>
          </div>
        </div>
        <div class="analysis-panel quality-{escape(source_quality)}">
          <span class="eyebrow">Analysis</span>
          <h3>운영 판단</h3>
          <p>{escape(admin_advice)}</p>
          <dl class="quality-list">
            <div><dt>HTML source</dt><dd>{escape(html_source)}</dd></div>
            <div><dt>Usage quality</dt><dd>{escape(usage_quality)}</dd></div>
            <div><dt>Cost quality</dt><dd>{escape(cost_quality)}</dd></div>
            <div><dt>Vision</dt><dd>{escape(str(meta.get("vision_used") or False))}</dd></div>
          </dl>
        </div>
        <div class="result-block">
          <div class="section-heading compact">
            <span class="eyebrow">AI Output</span>
            <h3>추출 요약</h3>
          </div>
          <pre>{_json_pretty(summary)}</pre>
        </div>
        <details class="apply-panel">
          <summary>DB 반영 위험 영역 열기</summary>
        <form method="post" action="/internal/admin/ai-test/apply" class="danger">
          <div>
            <span class="eyebrow danger-text">DB Apply</span>
            <h3>검토한 결과만 DB에 반영</h3>
            <p>AI를 다시 실행한 뒤 선택한 공지 1건만 업데이트합니다. Idempotency-Key는 제출 시 브라우저에서 자동 생성됩니다.</p>
          </div>
          <input type="hidden" name="notice_id" value="{notice_id}" />
          <label class="check-row"><input type="checkbox" name="include_vision" value="true" /> 이미지 포함(vision)</label>
          <label class="field">확인 문자열 <span>notice_id 또는 제목 일부</span><input name="confirmation" value="{notice_id}" /></label>
          <button class="button danger-button" type="submit" name="apply" value="true">DB 반영 실행</button>
        </form>
        </details>
        <details class="raw-panel"><summary>Raw JSON 보기</summary><pre>{_json_pretty(result)}</pre></details>
        """

    overall = cast(dict[str, object], dashboard.get("overall") or {})
    last_24h = cast(dict[str, object], dashboard.get("last_24h") or {})
    last_7d = cast(dict[str, object], dashboard.get("last_7d") or {})
    top = cast(list[dict[str, object]], dashboard.get("top_notices") or [])
    quality_note = (
        f"valid usage {escape(_format_number(overall.get('valid_usage_count')))}, "
        f"missing usage {escape(_format_number(overall.get('missing_usage_count')))}, "
        f"invalid usage {escape(_format_number(overall.get('invalid_usage_count')))}, "
        f"unavailable usage {escape(_format_number(overall.get('unavailable_usage_count')))}"
    )
    top_rows = "".join(
        "<tr>"
        f"<td class=\"title-cell\">{escape(str(item.get('title') or ''))}</td>"
        f"<td>{escape(str(item.get('college_code') or ''))}</td>"
        f"<td>{escape(str(item.get('model') or ''))}</td>"
        f"<td>{escape(_format_number(item.get('total_tokens')))}</td>"
        f"<td>{escape(str(item.get('estimated_cost_usd') or 'unknown'))}</td>"
        "</tr>"
        for item in top
    )
    if not top_rows:
        top_rows = '<tr><td colspan="5" class="table-empty">아직 집계된 AI 사용 기록이 없습니다.</td></tr>'
    message_html = f'<div class="message">{escape(message)}</div>' if message else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Token Cost Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-muted: #f8fafc;
      --border: #d8dee8;
      --border-strong: #b8c2d2;
      --text: #172033;
      --muted: #667085;
      --accent: #2457d6;
      --accent-dark: #1e45a8;
      --danger: #b42318;
      --danger-bg: #fff4f2;
      --danger-border: #f5b8b1;
      --success-bg: #ecfdf3;
      --success-border: #abefc6;
      --shadow: 0 18px 45px rgba(16, 24, 40, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      line-height: 1.5;
    }}
    .page {{ max-width: 1180px; margin: 0 auto; padding: 32px 24px 48px; }}
    .page-header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      margin-bottom: 24px;
    }}
    .page-header h1 {{ margin: 6px 0 8px; font-size: clamp(30px, 5vw, 44px); letter-spacing: -0.04em; }}
    .page-header p {{ max-width: 760px; margin: 0; color: var(--muted); font-size: 16px; }}
    .badge {{
      flex: 0 0 auto;
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 999px;
      padding: 8px 12px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr); gap: 20px; align-items: start; }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 22px;
    }}
    .section-heading {{ margin-bottom: 18px; }}
    .section-heading.compact {{ margin: 20px 0 10px; }}
    .section-heading h2, .section-heading h3 {{ margin: 4px 0 6px; letter-spacing: -0.02em; }}
    .section-heading p {{ margin: 0; color: var(--muted); }}
    .eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }}
    .field {{ display: grid; gap: 7px; margin: 14px 0; font-weight: 700; }}
    .field span {{ color: var(--muted); font-size: 13px; font-weight: 500; }}
    select, input:not([type="checkbox"]) {{
      width: 100%;
      min-height: 44px;
      border: 1px solid var(--border-strong);
      border-radius: 10px;
      background: var(--surface);
      color: var(--text);
      padding: 10px 12px;
      font: inherit;
    }}
    select:focus-visible, input:focus-visible, button:focus-visible, summary:focus-visible {{
      outline: 3px solid rgba(36, 87, 214, 0.22);
      outline-offset: 2px;
    }}
    .check-row {{ display: flex; align-items: center; gap: 10px; margin: 12px 0; color: var(--text); font-weight: 650; }}
    .check-row input {{ width: 18px; height: 18px; accent-color: var(--accent); }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      border: 0;
      border-radius: 10px;
      background: var(--accent);
      color: #fff;
      padding: 10px 16px;
      cursor: pointer;
      font-weight: 750;
    }}
    .button:hover {{ background: var(--accent-dark); }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .metric-card {{
      border: 1px solid var(--border);
      border-radius: 14px;
      background: var(--surface-muted);
      padding: 15px;
      min-width: 0;
    }}
    .metric-label {{ display: block; color: var(--muted); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; }}
    .metric-card strong {{ display: block; margin-top: 8px; font-size: 28px; letter-spacing: -0.04em; }}
    .metric-card small {{ display: block; margin-top: 4px; color: var(--muted); word-break: break-word; }}
    .result-metrics {{ margin-top: 18px; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      color: #e5e7eb;
      padding: 16px;
      border-radius: 14px;
      overflow: auto;
      max-height: 480px;
    }}
    .empty-state {{
      margin-top: 20px;
      border: 1px dashed var(--border-strong);
      border-radius: 16px;
      background: var(--surface-muted);
      padding: 24px;
    }}
    .empty-state h3 {{ margin: 6px 0; }}
    .empty-state p {{ margin: 0; color: var(--muted); }}
    .empty-kicker {{ color: var(--muted); font-size: 12px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }}
    .danger {{
      display: grid;
      gap: 8px;
      margin-top: 18px;
      border: 1px solid var(--danger-border);
      background: var(--danger-bg);
      padding: 18px;
      border-radius: 16px;
    }}
    .danger h3 {{ margin: 3px 0 6px; }}
    .danger p {{ margin: 0; color: #7a271a; }}
    .danger-text {{ color: var(--danger); }}
    .danger-button {{ background: var(--danger); }}
    .danger-button:hover {{ background: #912018; }}
    .message {{
      margin-bottom: 18px;
      border: 1px solid var(--success-border);
      background: var(--success-bg);
      border-radius: 12px;
      padding: 12px 14px;
      font-weight: 700;
    }}
    .analysis-panel {{
      margin-top: 16px;
      border: 1px solid var(--border);
      background: var(--surface-muted);
      border-radius: 14px;
      padding: 16px;
    }}
    .analysis-panel h3 {{ margin: 4px 0 6px; }}
    .analysis-panel p {{ margin: 0 0 12px; color: var(--text); font-weight: 650; }}
    .quality-warning {{ border-color: #fdb022; background: #fffaeb; }}
    .quality-blocked {{ border-color: var(--danger-border); background: var(--danger-bg); }}
    .quality-list {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; margin: 0; }}
    .quality-list div {{ min-width: 0; }}
    .quality-list dt {{ color: var(--muted); font-size: 12px; font-weight: 800; text-transform: uppercase; }}
    .quality-list dd {{ margin: 2px 0 0; font-weight: 700; word-break: break-word; }}
    .apply-panel {{
      margin-top: 16px;
      border: 1px solid var(--danger-border);
      border-radius: 16px;
      background: var(--danger-bg);
      padding: 14px;
    }}
    .apply-panel summary {{ color: var(--danger); }}
    .raw-panel {{ margin-top: 16px; }}
    summary {{ cursor: pointer; color: var(--accent); font-weight: 750; }}
    .dashboard-note {{ color: var(--muted); margin: 14px 0 16px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 14px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 720px; background: var(--surface); }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 11px 12px; text-align: left; vertical-align: top; }}
    th {{ background: var(--surface-muted); color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }}
    tr:last-child td {{ border-bottom: 0; }}
    .title-cell {{ min-width: 260px; font-weight: 650; }}
    .table-empty {{ color: var(--muted); text-align: center; padding: 28px; }}
    @media (max-width: 900px) {{
      .page {{ padding: 22px 14px 36px; }}
      .page-header {{ display: block; }}
      .badge {{ display: inline-flex; margin-top: 14px; }}
      .grid, .metric-grid, .quality-list {{ grid-template-columns: 1fr; }}
      .panel {{ padding: 18px; border-radius: 16px; }}
    }}
  </style>
  <script>
    document.addEventListener('submit', function (event) {{
      if (event.target.action.endsWith('/apply')) {{
        event.target.action = event.target.action + '?idempotency_key=' + crypto.randomUUID();
      }}
    }});
  </script>
</head>
<body>
  <main class="page">
    <header class="page-header">
      <div>
        <span class="eyebrow">Local Admin</span>
        <h1>AI Token Cost Console</h1>
        <p>공지 1건을 드라이런하고 토큰 사용량, 추정 비용, 본문 소스 신뢰도, usage 품질을 함께 확인합니다.</p>
        <div hidden>
        <h1>AI 관리자</h1>
        <p>공지 1건을 안전하게 드라이런하고, 토큰 비용과 추출 결과를 확인한 뒤 필요한 경우에만 DB에 반영합니다.</p>
      </div>
      <span class="badge">localhost only · remote fetch disabled</span>
      </div>
    </header>
    {message_html}
    <div class="grid">
      <section class="panel">
      <div class="section-heading">
        <span class="eyebrow">Step 1</span>
        <h2>공지 선택 및 드라이런</h2>
        <p>드라이런은 DB, 큐, 공지 상태를 변경하지 않습니다.</p>
      </div>
      <form method="post" action="/internal/admin/ai-test/run">
        <label class="field">최근 공지 <span>AI 테스트에 사용할 공지 1건</span><select name="notice_id" required>{options_html}</select></label>
        <label class="check-row"><input type="checkbox" name="include_vision" value="true" /> 이미지 포함(vision)</label>
        <button class="button" type="submit">드라이런 실행</button>
      </form>
      {result_html}
    </section>
    <section class="panel">
      <div class="section-heading">
        <span class="eyebrow">Usage</span>
        <h2>Token Dashboard</h2>
        <p>최근 AI 실행 기록의 토큰 사용량과 비용 추정치를 빠르게 확인합니다.</p>
      </div>
      <div class="metric-grid">
        <div class="metric-card"><span class="metric-label">Overall</span><strong>{escape(_format_number(overall.get("total_tokens")))}</strong><small>{escape(_format_number(overall.get("call_count")))} calls</small></div>
        <div class="metric-card"><span class="metric-label">24h</span><strong>{escape(_format_number(last_24h.get("total_tokens")))}</strong><small>{escape(_format_number(last_24h.get("call_count")))} calls</small></div>
        <div class="metric-card"><span class="metric-label">7d</span><strong>{escape(_format_number(last_7d.get("total_tokens")))}</strong><small>{escape(_format_number(last_7d.get("call_count")))} calls</small></div>
      </div>
      <p class="dashboard-note">{quality_note}</p>
      <div class="section-heading compact">
        <h3>Top 20</h3>
      </div>
      <div class="table-wrap"><table><thead><tr><th>제목</th><th>college</th><th>model</th><th>tokens</th><th>cost</th></tr></thead><tbody>{top_rows}</tbody></table></div>
      <details class="raw-panel"><summary>Dashboard Raw JSON 보기</summary><pre>{_json_pretty(dashboard)}</pre></details>
    </section>
    </div>
  </main>
</body>
</html>"""


def _map_result_to_status(result: TriggerCrawlResult) -> int:
    """TriggerCrawlResult.result_kind에 따라 HTTP status code 반환. Router 전용."""
    if result.result_kind == TriggerCrawlResultKind.cached:
        return 202
    if result.result_kind == TriggerCrawlResultKind.success:
        return 200
    # partial_failure | infra_unavailable: RELEASE_GATE P0 (부분 실패를 200으로 숨기지 않음)
    return 503


def _rate_limit_headers() -> dict[str, str]:
    return {"Retry-After": str(RATE_LIMIT_RETRY_AFTER_SECONDS)}


def _rate_limit_identity(request: Request) -> str:
    """
    pre-auth rate limit용 식별자.
    get_client_ip가 없으면 direct peer host, 그것도 없으면 unknown 사용.
    """
    ip = get_client_ip(request)
    if ip:
        return ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _enforce_rate_limit_or_503(
    redis_client: RedisAsyncio | None,
    *,
    identifier: str,
    max_requests: int,
) -> bool:
    """공통 rate limit 검사. 백엔드 장애 시 503으로 fail-closed."""
    try:
        return await check_rate_limit(
            redis_client,
            identifier=identifier,
            max_requests=max_requests,
            window_seconds=60,
            require_redis=settings.api_rate_limit_require_redis,
        )
    except RateLimitUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable. Try again later.",
        ) from None


def _log_internal_auth_failure(
    request: Request,
    reason: str,
    error: Exception | None = None,
) -> None:
    """구조화 로그로 내부 인증 실패 기록. 시크릿 값·평문 IP는 로깅하지 않으며, IP는 HMAC만 기록."""
    endpoint = getattr(request.url, "path", "unknown") if request else "unknown"
    metrics.increment(
        metrics.INTERNAL_AUTH_FAILED_TOTAL,
        labels={"endpoint": endpoint, "reason": reason},
    )
    client_ip = get_client_ip(request) if request else None
    try:
        ip_hmac_val, ip_hmac_key_version = compute_ip_hmac(client_ip or "")
    except Exception:
        ip_hmac_val, ip_hmac_key_version = "", "unknown"
    request_id = getattr(request.state, "request_id", None) if request else None
    extra = {
        "path": endpoint,
        "ip_hmac": ip_hmac_val or "(no key)",
        "ip_hmac_key_version": ip_hmac_key_version,
        "request_id": request_id,
        "reason": reason,
    }
    if error is not None:
        logger.warning("internal auth failed", extra=extra, exc_info=error)
    else:
        logger.warning("internal auth failed", extra=extra)


def _authorize_internal_trigger(
    request: Request,
    x_crawl_trigger_secret: str | None,
    authorization: str | None,
) -> None:
    """내부 트리거 시크릿 검사. 실패 시 HTTPException 발생."""
    try:
        check_crawl_trigger_secret(x_crawl_trigger_secret, authorization)
    except CrawlTriggerNotConfiguredError as e:
        _log_internal_auth_failure(request, reason="trigger_not_configured", error=e)
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable. Try again later.",
        ) from None
    except InvalidCrawlTriggerSecretError as e:
        _log_internal_auth_failure(request, reason="invalid_or_missing_secret", error=e)
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing crawl trigger secret",
        ) from None


def _require_client_ip(request: Request) -> str:
    """Fail-closed: if client IP cannot be resolved, return 503."""
    client_ip = get_client_ip(request)
    if client_ip is None:
        raise HTTPException(
            status_code=503,
            detail="Client identity could not be determined.",
        )
    return client_ip


def _require_local_admin_request(request: Request) -> str:
    """Local-only admin pages. Production is hidden, unresolved IP fails closed."""
    if (settings.environment or "").strip().lower() == "production":
        raise HTTPException(status_code=404, detail="Not found")
    client_ip = get_client_ip(request)
    if client_ip is None:
        raise HTTPException(status_code=503, detail="Client identity could not be determined.")
    if client_ip not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="AI admin is allowed only from localhost")
    return client_ip


async def _apply_internal_preauth_limit(
    request: Request,
    redis_client: RedisAsyncio | None,
    *,
    endpoint: str,
) -> None:
    identity = _rate_limit_identity(request)
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=f"internal_preauth:{endpoint}:{identity}",
        max_requests=settings.internal_preauth_rate_limit_per_minute,
    )
    if allowed:
        return
    metrics.increment(
        metrics.INTERNAL_PREAUTH_RATE_LIMITED_TOTAL,
        labels={"endpoint": endpoint},
    )
    raise HTTPException(
        status_code=429,
        detail="Too many internal requests, please try again later.",
        headers=_rate_limit_headers(),
    )


async def _authorize_with_fail_limit(
    request: Request,
    redis_client: RedisAsyncio | None,
    *,
    endpoint: str,
    x_crawl_trigger_secret: str | None,
    authorization: str | None,
) -> None:
    try:
        _authorize_internal_trigger(request, x_crawl_trigger_secret, authorization)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        identity = _rate_limit_identity(request)
        allowed = await _enforce_rate_limit_or_503(
            redis_client,
            identifier=f"internal_auth_fail:{endpoint}:{identity}",
            max_requests=settings.internal_auth_fail_rate_limit_per_minute,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many internal authentication failures, please try again later.",
                headers=_rate_limit_headers(),
            ) from None
        raise


async def _apply_ai_admin_rate_limit(
    request: Request,
    redis_client: RedisAsyncio | None,
    *,
    endpoint: str,
) -> None:
    client_ip = _require_local_admin_request(request)
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=f"internal_ai_admin:{endpoint}:{client_ip}",
        max_requests=settings.internal_ai_admin_rate_limit_per_minute,
    )
    if allowed:
        return
    raise HTTPException(
        status_code=429,
        detail="Too many AI admin requests, please try again later.",
        headers=_rate_limit_headers(),
    )


def _ai_admin_http_error(exc: AiAdminError) -> HTTPException:
    if isinstance(exc, AiAdminNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AiAdminConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AiAdminDependencyUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, AiAdminValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="AI admin operation failed")


@router.post("/trigger-crawl")
async def post_trigger_crawl(
    request: Request,
    college_code: str | None = Query(
        None,
        description=(
            "단과대 코드. 생략 시 전체 순차 enqueue. "
            f"허용 값: {college_codes_for_openapi()}. "
            "목록에 없는 값은 400 (code COLLEGE_NOT_FOUND)."
        ),
    ),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
    internal_crawl_service: InternalCrawlService = Depends(get_internal_crawl_service),
) -> JSONResponse:
    """
    크롤 태스크 enqueue. 보안 키는 Header만 필수. college별 Redis 분산락(SET NX EX)으로 중복 enqueue 방지.
    Idempotency-Key 있으면 동일 키 재요청 시 202 + 캐시된 결과.
    일부·전체 enqueue 실패 시 503 + JSON(enqueued/skipped/failed, code). RELEASE_GATE P0와 정합.
    P1: 인증 후 rate-limit 적용. 식별자는 get_client_ip(프록시 대응) 사용.
    """
    endpoint = "/internal/trigger-crawl"
    await _apply_internal_preauth_limit(request, redis_client, endpoint=endpoint)
    await _authorize_with_fail_limit(
        request,
        redis_client,
        endpoint=endpoint,
        x_crawl_trigger_secret=x_crawl_trigger_secret,
        authorization=authorization,
    )
    client_ip = _require_client_ip(request)
    rate_identifier = f"internal_trigger_crawl:{client_ip}"
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=rate_identifier,
        max_requests=settings.internal_trigger_crawl_rate_limit_per_minute,
    )
    if not allowed:
        _log_internal_auth_failure(
            request,
            reason="rate_limited_trigger_crawl",
            error=None,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many internal trigger requests, please try again later.",
            headers=_rate_limit_headers(),
        )

    key_stripped = normalize_trigger_idempotency_key(idempotency_key)
    cmd = TriggerCrawlCmd(
        college_code=college_code,
        idempotency_key=key_stripped,
        client_ip=client_ip,
    )
    result = await internal_crawl_service.trigger(cmd)
    status_code = _map_result_to_status(result)
    return JSONResponse(status_code=status_code, content=result.payload)


@router.get("/crawl-stats")
async def get_crawl_stats(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="최근 N건"),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
    crawl_stats_service: CrawlStatsService = Depends(get_crawl_stats_service),
) -> CrawlStatsResponse:
    """
    최근 크롤 실행 이력. 단과대별 last_run_at, status, notices_upserted, has_error.
    보안 키 필수. Header만 사용 (X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
    인증 실패 시 공통 _authorize_internal_trigger 로깅/응답으로 감사 추적 일관성 유지.
    P1: 인증 후 rate-limit. 식별자는 get_client_ip(프록시 대응) 사용.
    """
    endpoint = "/internal/crawl-stats"
    await _apply_internal_preauth_limit(request, redis_client, endpoint=endpoint)
    await _authorize_with_fail_limit(
        request,
        redis_client,
        endpoint=endpoint,
        x_crawl_trigger_secret=x_crawl_trigger_secret,
        authorization=authorization,
    )
    client_ip = _require_client_ip(request)
    rate_identifier = f"internal_crawl_stats:{client_ip}"
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=rate_identifier,
        max_requests=settings.internal_crawl_stats_rate_limit_per_minute,
    )
    if not allowed:
        _log_internal_auth_failure(
            request,
            reason="rate_limited_crawl_stats",
            error=None,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many internal stats requests, please try again later.",
            headers=_rate_limit_headers(),
        )
    state = getattr(request.app.state, "operational_mode", "NORMAL")
    key_parts = ("crawl_stats", str(limit), "v3")
    cached, should_refresh, lock_token = await get_cached_with_soft_ttl(redis_client, *key_parts)

    # Fresh hit: 즉시 반환
    if cached is not None and not should_refresh:
        metrics.increment(metrics.READ_CACHE_FRESH_HIT_TOTAL)
        return CrawlStatsResponse.model_validate(cached)

    # Stale + lock 미획득: stale 즉시 반환
    if cached is not None and should_refresh and lock_token is None:
        metrics.increment(metrics.READ_CACHE_STALE_HIT_TOTAL)
        return CrawlStatsResponse.model_validate(cached)

    # Hard miss + lock 미획득: 짧게 wait 후 재조회
    if cached is None and lock_token is None:
        metrics.increment(metrics.READ_CACHE_WAIT_TOTAL)
        wait_ms = getattr(settings, "read_cache_wait_for_fresh_ms", 1000)
        cached, should_refresh, lock_token = await wait_for_cached(redis_client, wait_ms, *key_parts)
        if cached is not None:
            return CrawlStatsResponse.model_validate(cached)
        if state == "DEGRADED":
            raise HTTPException(
                status_code=503,
                detail="Service degraded; cached data unavailable. Try again later.",
                headers={"Retry-After": "60"},
            )
        # 재조회 후에도 miss면 한 번 더 락 획득 시도. 성공 시에만 refresh, 실패 시 503(stampede 방지)
        cached, should_refresh, lock_token = await get_cached_with_soft_ttl(redis_client, *key_parts)
        if cached is not None:
            return CrawlStatsResponse.model_validate(cached)
        if lock_token is None:
            raise HTTPException(
                status_code=503,
                detail="Cache unavailable; try again later.",
                headers={"Retry-After": "2"},
            )

    # should_refresh && lock_token 있음: DB 조회 후 갱신 (락 없이 DB 직접 치는 경로 제거)
    if should_refresh and lock_token is not None:
        metrics.increment(metrics.READ_CACHE_MISS_TOTAL if cached is None else metrics.READ_CACHE_STALE_HIT_TOTAL)
        metrics.increment(metrics.READ_CACHE_REFRESH_TOTAL)
        maker = getattr(request.app.state, "async_session_maker", None)
        async with read_only_session_cm(maker) as session:
            # ReadOnlySessionWrapper는 AsyncSession을 래핑하므로 타입 체커를 위해 캐스팅한다.
            result = await crawl_stats_service.get_crawl_stats(cast(AsyncSession, session), limit=limit)
        response = CrawlStatsResponse(
            runs=[
                CrawlRunStatsItem(
                    college_code=r.college_code,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    status=r.status,
                    notices_upserted=r.notices_upserted,
                    has_error=r.has_error,
                )
                for r in result.runs
            ],
            limit=result.limit,
            source_freshness=[
                CrawlSourceFreshnessStatsItem(
                    college_code=s.college_code,
                    last_attempt_status=s.last_attempt_status,
                    last_attempt_started_at=s.last_attempt_started_at,
                    last_attempt_finished_at=s.last_attempt_finished_at,
                    total_docs=s.total_docs,
                    is_stale=s.is_stale,
                )
                for s in result.source_freshness
            ],
        )
        await set_cached_with_soft_ttl(redis_client, *key_parts, value=response.model_dump())
        await release_cached_lock(redis_client, *key_parts, token=lock_token)
        return response

    if cached is not None:
        return CrawlStatsResponse.model_validate(cached)
    raise HTTPException(
        status_code=503,
        detail="Service degraded; cached data unavailable. Try again later.",
        headers={"Retry-After": "60"},
    )


@router.get("/preview/engineering", response_class=HTMLResponse)
async def get_engineering_preview_page(
    request: Request,
    session: SessionDep,
    limit: int = Query(30, ge=1, le=100, description="미리보기 최대 공지 수"),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    preview_service: NoticePreviewService = Depends(get_notice_preview_service),
) -> HTMLResponse:
    """
    공대(engineering) 공지 임시 검수 HTML.
    제목/게시일/본문/이미지/첨부/지원자격/날짜/대분류/소분류를 한 화면에서 확인한다.
    """
    _authorize_internal_trigger(request, x_crawl_trigger_secret, authorization)
    rows = await preview_service.get_engineering_preview(session, limit=limit)
    return HTMLResponse(content=_render_engineering_preview_html(rows, limit=limit), status_code=200)


@router.get("/public-preview/engineering", response_class=HTMLResponse)
async def get_engineering_public_preview_page(
    request: Request,
    session: SessionDep,
    limit: int = Query(30, ge=1, le=100, description="미리보기 최대 공지 수"),
    preview_service: NoticePreviewService = Depends(get_notice_preview_service),
) -> HTMLResponse:
    """
    로컬 검수용 임시 공개 미리보기. 개발 환경 + localhost에서만 허용한다.
    """
    client_host = (request.client.host if request.client else "") or ""
    if (settings.environment or "").strip().lower() == "production":
        raise HTTPException(status_code=404, detail="Not found")
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Public preview is allowed only from localhost")
    rows = await preview_service.get_engineering_preview(session, limit=limit)
    return HTMLResponse(content=_render_engineering_preview_html(rows, limit=limit), status_code=200)


@router.get("/admin/ai-test", response_class=HTMLResponse)
async def get_ai_admin_page(
    request: Request,
    session: ReadOnlySessionDep,
    limit: int = Query(30, ge=1, le=100, description="최근 공지 수"),
    ai_admin_service: AiAdminService = Depends(get_ai_admin_service),
) -> HTMLResponse:
    """로컬 전용 AI 테스트/토큰 대시보드."""
    _require_local_admin_request(request)
    notices = await ai_admin_service.list_notice_options(cast(AsyncSession, session), limit=limit)
    dashboard = await ai_admin_service.usage_dashboard(
        cast(AsyncSession, session),
        period_days=30,
        limit=settings.ai_admin_dashboard_max_rows,
    )
    return HTMLResponse(
        content=_render_ai_admin_html(
            notices=_to_plain_list(cast(list[object], notices)),
            dashboard=_to_plain(dashboard),
        ),
        status_code=200,
    )


@router.post("/admin/ai-test/run", response_class=HTMLResponse)
async def post_ai_admin_dry_run(
    request: Request,
    session: ReadOnlySessionDep,
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
    ai_admin_service: AiAdminService = Depends(get_ai_admin_service),
) -> HTMLResponse:
    """로컬 전용 공지 1건 AI 드라이런. DB/큐/상태를 변경하지 않는다."""
    await _apply_ai_admin_rate_limit(request, redis_client, endpoint="/internal/admin/ai-test/run")
    form_data = await _admin_form_data(request)
    notice_id = form_data.get("notice_id") or ""
    include_vision = _form_bool(form_data, "include_vision")
    try:
        result = await ai_admin_service.run_dry_run(
            cast(AsyncSession, session),
            notice_id=notice_id,
            include_vision=include_vision,
        )
        notices = await ai_admin_service.list_notice_options(cast(AsyncSession, session), limit=30)
        dashboard = await ai_admin_service.usage_dashboard(
            cast(AsyncSession, session),
            period_days=30,
            limit=settings.ai_admin_dashboard_max_rows,
        )
    except AiAdminError as exc:
        raise _ai_admin_http_error(exc) from exc
    return HTMLResponse(
        content=_render_ai_admin_html(
            notices=_to_plain_list(cast(list[object], notices)),
            dashboard=_to_plain(dashboard),
            result=result_to_payload(result),
        ),
        status_code=200,
    )


@router.post("/admin/ai-test/apply", response_class=HTMLResponse)
async def post_ai_admin_apply(
    request: Request,
    session: SessionDep,
    idempotency_key: str | None = Query(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
    ai_admin_service: AiAdminService = Depends(get_ai_admin_service),
) -> HTMLResponse:
    """로컬 전용 공지 1건 AI 실행 후 DB 반영. Idempotency-Key와 notice lock이 필수."""
    await _apply_ai_admin_rate_limit(request, redis_client, endpoint="/internal/admin/ai-test/apply")
    form_data = await _admin_form_data(request)
    notice_id = form_data.get("notice_id") or ""
    confirmation = form_data.get("confirmation") or ""
    include_vision = _form_bool(form_data, "include_vision")
    if form_data.get("apply") != "true":
        raise HTTPException(status_code=400, detail="apply=true is required")
    claim = None
    try:
        claim, cached = await ai_admin_service.prepare_apply_claim(
            redis_client,
            notice_id=notice_id,
            idempotency_key=idempotency_key or "",
        )
        if cached is not None:
            if cached.get("status") == "in_progress":
                raise HTTPException(status_code=409, detail="Admin apply is already in progress for this key")
            notices = await ai_admin_service.list_notice_options(session, limit=30)
            dashboard = await ai_admin_service.usage_dashboard(
                session,
                period_days=30,
                limit=settings.ai_admin_dashboard_max_rows,
            )
            return HTMLResponse(
                content=_render_ai_admin_html(
                    notices=_to_plain_list(cast(list[object], notices)),
                    dashboard=_to_plain(dashboard),
                    result=cached,
                    message="Idempotency-Key replay: cached apply result.",
                ),
                status_code=202,
            )
        if claim is None:
            raise HTTPException(status_code=409, detail="Admin apply claim was not created")
        result = await ai_admin_service.run_apply(
            session,
            claim=claim,
            include_vision=include_vision,
            confirmation=confirmation,
        )
        await session.commit()
        payload = result_to_payload(result)
        await ai_admin_service.complete_apply(redis_client, claim, payload)
        notices = await ai_admin_service.list_notice_options(session, limit=30)
        dashboard = await ai_admin_service.usage_dashboard(
            session,
            period_days=30,
            limit=settings.ai_admin_dashboard_max_rows,
        )
    except HTTPException:
        await session.rollback()
        await ai_admin_service.abort_apply(redis_client, claim)
        raise
    except AiAdminError as exc:
        await session.rollback()
        await ai_admin_service.abort_apply(redis_client, claim)
        raise _ai_admin_http_error(exc) from exc
    except Exception:
        await session.rollback()
        await ai_admin_service.abort_apply(redis_client, claim)
        logger.exception("AI admin apply failed")
        raise
    return HTMLResponse(
        content=_render_ai_admin_html(
            notices=_to_plain_list(cast(list[object], notices)),
            dashboard=_to_plain(dashboard),
            result=payload,
            message="DB 반영이 완료되었습니다.",
        ),
        status_code=200,
    )


@router.get("/admin/token-dashboard")
async def get_ai_admin_token_dashboard(
    request: Request,
    session: ReadOnlySessionDep,
    period_days: int = Query(30, ge=1, le=365),
    limit: int = Query(5000, ge=100, le=100000),
    ai_admin_service: AiAdminService = Depends(get_ai_admin_service),
) -> JSONResponse:
    """로컬 전용 토큰/비용 대시보드 JSON."""
    _require_local_admin_request(request)
    dashboard = await ai_admin_service.usage_dashboard(
        cast(AsyncSession, session),
        period_days=period_days,
        limit=limit,
    )
    return JSONResponse(content=_to_plain(dashboard))


def _metrics_allowed_client_ip(request: Request) -> bool:
    """
    METRICS_ALLOWED_IPS가 설정된 경우 해당 IP만 허용. 미설정(빈 값) 시 모든 IP 차단(fail-closed).
    프록시 환경: get_client_ip 사용으로 X-Forwarded-For + trusted_proxy 검사 후 실제 클라이언트 IP로
    allowlist 검사. request.client.host만 쓰면 프록시 IP 하나로 통과되어 외부 트래픽이 우회할 수 있음.
    """
    allowed_ips_str = (settings.metrics_allowed_ips or "").strip() or ""
    if not allowed_ips_str.strip():
        return False
    allowed = {ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()}
    client_ip = get_client_ip(request)
    if client_ip is None:
        return False
    return client_ip in allowed


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    """Prometheus 텍스트 포맷으로 메트릭 노출. METRICS_ALLOWED_IPS 미설정(빈 값) 시 모든 IP 차단(fail-closed)."""
    if not _metrics_allowed_client_ip(request):
        raise HTTPException(status_code=403, detail="Metrics access not allowed for this client")
    data = metrics.get_all()
    lines: list[str] = []
    for name, val in data["counters"].items():
        lines.append(f"{name} {val}")
    for name, val in data["gauges"].items():
        lines.append(f"{name} {val}")
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")
