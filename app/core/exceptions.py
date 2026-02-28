"""도메인/애플리케이션 예외. 전역 핸들러에서만 HTTP로 변환하며, 서비스는 HTTP를 알지 않음."""


class DICEEError(Exception):
    """프로젝트 공통 도메인 예외 베이스."""

    pass


class CollegeNotFoundError(DICEEError, ValueError):
    """미등록 또는 잘못된 college_code. 전역 핸들러에서 400으로 매핑."""

    pass


class InternalCrawlError(DICEEError):
    """내부 크롤 API용 비즈니스/인프라 오류 공통 부모. 전역 핸들러에서 503으로 매핑."""

    pass


class RedisInfraError(InternalCrawlError):
    """Redis 락/멱등 등 인프라 불가 시 사용. RedisLockUnavailableError 등이 상속."""

    pass
