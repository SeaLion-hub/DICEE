"""간단한 iCalendar(text/calendar) 생성. 외부 의존성 없음."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n").replace("\r", "")


def _dt_utc_prop(name: str, dt: datetime) -> str:
    u = dt.astimezone(UTC)
    return f"{name}:{u.strftime('%Y%m%dT%H%M%SZ')}"


def build_ics_from_calendar_payload(payload: dict[str, Any], *, calendar_uid: str) -> str:
    """payload는 build_calendar_payload 결과와 동일 키."""
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DICEE//Calendar//KO",
        "CALSCALE:GREGORIAN",
    ]
    for item in payload.get("notice_schedules") or []:
        sid = item["schedule_id"]
        uid = f"ns-{sid}@dicee"
        title = _ics_escape(str(item.get("title") or "Notice"))
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"SUMMARY:{title}")
        st = item.get("start_at")
        et = item.get("end_at")
        if isinstance(st, datetime):
            if item.get("is_all_day"):
                d = st.astimezone(UTC).date()
                lines.append(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}")
                if isinstance(et, datetime):
                    d_end = et.astimezone(UTC).date()
                    lines.append(f"DTEND;VALUE=DATE:{d_end.strftime('%Y%m%d')}")
            else:
                lines.append(_dt_utc_prop("DTSTART", st))
                if isinstance(et, datetime):
                    lines.append(_dt_utc_prop("DTEND", et))
        fb = item.get("schedule_text_fallback")
        if fb:
            lines.append(f"DESCRIPTION:{_ics_escape(str(fb))}")
        lines.append("END:VEVENT")

    for item in payload.get("user_events") or []:
        eid = item["id"]
        uid = f"uce-{eid}-{calendar_uid}@dicee"
        title = _ics_escape(str(item.get("title") or "Event"))
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"SUMMARY:{title}")
        st = item.get("start_at")
        et = item.get("end_at")
        if isinstance(st, datetime):
            lines.append(_dt_utc_prop("DTSTART", st))
        if isinstance(et, datetime):
            lines.append(_dt_utc_prop("DTEND", et))
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
