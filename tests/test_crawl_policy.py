"""crawl_policy: CrawlErrorTracker 임계치·CrawlThresholdExceeded 검증."""

import pytest

from app.services.crawl_policy import (
    PARSER_CONSECUTIVE_FAILURES_THRESHOLD,
    CrawlErrorTracker,
    CrawlThresholdExceeded,
)


def test_tracker_consecutive_failure_threshold():
    """연속 파서 실패가 PARSER_CONSECUTIVE_FAILURES_THRESHOLD(5)회 도달 시 CrawlThresholdExceeded."""
    tracker = CrawlErrorTracker()
    # 비율 임계치(3회 이상 시도 시 parser_failures/attempted > 0.3)를 피하려면
    # 성공을 많이 넣어 attempted를 키우고, 연속 5회 파서 실패만 발생시킨다.
    for _ in range(12):
        tracker.record_attempt()
        tracker.record_success()
    for _ in range(4):
        tracker.record_attempt()
        assert tracker.record_parser_failure() is None

    tracker.record_attempt()
    exc = tracker.record_parser_failure()
    assert isinstance(exc, CrawlThresholdExceeded)
    assert exc.consecutive == PARSER_CONSECUTIVE_FAILURES_THRESHOLD
    assert exc.parser_failures == 5
    assert "consecutive parser failures" in str(exc)


def test_tracker_parser_failure_ratio_threshold():
    """attempted >= 3 이고 parser_failures/attempted > 0.3 이면 CrawlThresholdExceeded."""
    tracker = CrawlErrorTracker()
    tracker.record_attempt()
    tracker.record_parser_failure()
    tracker.record_attempt()
    tracker.record_success()
    tracker.record_attempt()
    exc = tracker.record_parser_failure()
    assert isinstance(exc, CrawlThresholdExceeded)
    assert exc.attempted == 3
    assert exc.parser_failures == 2
    assert 2 / 3 > 0.3
    assert "parser failure ratio" in str(exc)


def test_tracker_network_or_skip_resets_consecutive():
    """record_network_or_skip 호출 시 consecutive_parser_failures 리셋."""
    tracker = CrawlErrorTracker()
    tracker.record_attempt()
    tracker.record_parser_failure()
    tracker.record_parser_failure()
    tracker.record_network_or_skip()
    assert tracker.consecutive_parser_failures == 0
    tracker.record_attempt()
    assert tracker.record_parser_failure() is None


def test_tracker_success_resets_consecutive():
    """record_success 호출 시 consecutive_parser_failures 리셋."""
    tracker = CrawlErrorTracker()
    tracker.record_attempt()
    tracker.record_parser_failure()
    tracker.record_parser_failure()
    tracker.record_success()
    assert tracker.consecutive_parser_failures == 0


def test_crawl_threshold_exceeded_attributes():
    """CrawlThresholdExceeded 인스턴스에 attempted, parser_failures, consecutive 속성."""
    exc = CrawlThresholdExceeded(
        message="test",
        attempted=10,
        parser_failures=4,
        consecutive=3,
    )
    assert exc.attempted == 10
    assert exc.parser_failures == 4
    assert exc.consecutive == 3
    assert "test" in str(exc)
