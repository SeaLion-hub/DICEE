"""Pytest fixtures. 테스트 시 DB 없이 실행 가능하도록 환경 조정."""

import os

import pytest
from fastapi.testclient import TestClient

# CI에서 DATABASE_URL이 주입되면 그대로 사용. 로컬에서 비어 있으면 DB 없이 부팅 가능하도록 빈 문자열.
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = ""
# Settings Fail-fast 대비: 테스트 시 필수 Auth env 설정
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient. DB 없이 /health 등 테스트용."""
    from app.main import app
    return TestClient(app)
