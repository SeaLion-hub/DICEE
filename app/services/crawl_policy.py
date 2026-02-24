"""크롤 정책: 파서 실패 임계치·예외. Orchestration에서 import해 사용."""

# 파서/구조 예외 임계치: 초과 시 태스크 실패(raise). 정책 B.
PARSER_FAILURE_RATIO_THRESHOLD = 0.3  # 시도 대비 파서 실패 비율 상한
PARSER_CONSECUTIVE_FAILURES_THRESHOLD = 5  # 연속 파서 실패 횟수 상한


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
