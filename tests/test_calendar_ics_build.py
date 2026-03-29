"""ICS 빌더."""

from datetime import UTC, datetime

from app.services.calendar_ics_service import build_ics_from_calendar_payload


def test_build_ics_minimal() -> None:
    payload = {
        "notice_schedules": [
            {
                "schedule_id": "550e8400-e29b-41d4-a716-446655440000",
                "notice_id": "660e8400-e29b-41d4-a716-446655440001",
                "title": "Test;Event",
                "schedule_type": "event",
                "start_at": datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
                "end_at": datetime(2026, 3, 15, 13, 0, tzinfo=UTC),
                "is_all_day": False,
                "schedule_text_fallback": None,
            }
        ],
        "user_events": [],
    }
    text = build_ics_from_calendar_payload(payload, calendar_uid="u1")
    assert "BEGIN:VCALENDAR" in text
    assert "END:VCALENDAR" in text
    assert "Test\\;Event" in text or "Test" in text
