"""크롤 정책: 파서 실패 임계치·예외·에러 카운트 캡슐화. Orchestration에서 import해 사용."""

# 파서/구조 예외 임계치: 초과 시 태스크 실패(raise). 정책 B.
PARSER_FAILURE_RATIO_THRESHOLD = 0.3  # 시도 대비 파서 실패 비율 상한
PARSER_CONSECUTIVE_FAILURES_THRESHOLD = 5  # 연속 파서 실패 횟수 상한


class CrawlErrorTracker:
    """
    에러 카운트(attempted, parser_failures, consecutive_parser_failures)와 임계치 체크를 캡슐화.
    가변 상태를 인자로 넘기지 않고, 이 클래스가 소유. sync/async 공통 사용.
    """

    __slots__ = ("attempted", "parser_failures", "consecutive_parser_failures")

    def __init__(self) -> None:
        self.attempted = 0
        self.parser_failures = 0
        self.consecutive_parser_failures = 0

    def record_attempt(self) -> None:
        self.attempted += 1

    def record_network_or_skip(self) -> None:
        self.consecutive_parser_failures = 0

    def record_parser_failure(self) -> "CrawlThresholdExceeded | None":
        self.parser_failures += 1
        self.consecutive_parser_failures += 1
        if self.consecutive_parser_failures >= PARSER_CONSECUTIVE_FAILURES_THRESHOLD:
            return CrawlThresholdExceeded(
                f"consecutive parser failures {self.consecutive_parser_failures} >= {PARSER_CONSECUTIVE_FAILURES_THRESHOLD}",
                attempted=self.attempted,
                parser_failures=self.parser_failures,
                consecutive=self.consecutive_parser_failures,
            )
        if self.attempted >= 3 and (self.parser_failures / self.attempted) > PARSER_FAILURE_RATIO_THRESHOLD:
            return CrawlThresholdExceeded(
                f"parser failure ratio {self.parser_failures}/{self.attempted} > {PARSER_FAILURE_RATIO_THRESHOLD}",
                attempted=self.attempted,
                parser_failures=self.parser_failures,
                consecutive=self.consecutive_parser_failures,
            )
        return None

    def record_success(self) -> None:
        self.consecutive_parser_failures = 0


class CrawlThresholdExceeded(Exception):
    """파서 실패 비율 또는 연속 실패 횟수가 임계치를 초과함. 태스크 실패 처리."""

    def __init__(
        self,
        message: str,
        attempted: int,
        parser_failures: int,
        consecutive: int,
    ):
        super().__init__(message)
        self.attempted = attempted
        self.parser_failures = parser_failures
        self.consecutive = consecutive
