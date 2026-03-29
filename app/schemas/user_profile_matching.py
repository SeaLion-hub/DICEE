"""Re-export: 프로필 계약은 domain.contracts (import-linter: services는 schemas 미참조)."""

from app.domain.contracts.user_profile_matching_contracts import (
    UserMeResponse,
    UserProfileForMatching,
    UserProfileMatchingPatch,
)

__all__ = ["UserMeResponse", "UserProfileForMatching", "UserProfileMatchingPatch"]
