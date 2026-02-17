"""Pytest fixtures. 테스트 시 DB 없이 실행 가능하도록 환경 조정."""

import os

import pytest
from fastapi.testclient import TestClient

# CI/테스트: DATABASE_URL 비우면 DB 초기화 생략, 앱 부팅 가능 (.env override)
os.environ["DATABASE_URL"] = ""
# auth_service create_jwt_pair 테스트용
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest")


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient. DB 없이 /health 등 테스트용."""
    from app.main import app
    return TestClient(app)
