"""Setup-token redemption and booth enrollment (no /etc writes)."""

import os
import time

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.database import get_db
from shared.config import get_settings


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, tmp_path, monkeypatch):
    setup_token = tmp_path / "setup-token"
    enroll_token = tmp_path / "enroll-token"
    monkeypatch.setenv("SETUP_TOKEN_PATH", str(setup_token))
    monkeypatch.setenv("ENROLL_TOKEN_PATH", str(enroll_token))
    monkeypatch.setenv("INTERNAL_API_KEY", "enroll-key")
    get_settings.cache_clear()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, setup_token, enroll_token

    app.dependency_overrides.clear()
    get_settings.cache_clear()


class TestRedeemSetupToken:
    async def test_valid_token_creates_session_and_deletes_token(self, client):
        http, setup_token, _ = client
        setup_token.write_text("valid-token", encoding="utf-8")

        response = await http.post(
            "/api/setup/redeem-token", json={"token": "valid-token"}
        )

        assert response.status_code == 200
        assert "parking_setup_session" in response.cookies
        assert setup_token.exists() is False

    async def test_invalid_token_is_rejected(self, client):
        http, setup_token, _ = client
        setup_token.write_text("valid-token", encoding="utf-8")

        response = await http.post(
            "/api/setup/redeem-token", json={"token": "wrong-token"}
        )

        assert response.status_code == 401
        assert setup_token.exists() is True

    async def test_expired_token_is_gone_and_removed(self, client):
        http, setup_token, _ = client
        setup_token.write_text("old-token", encoding="utf-8")
        old = time.time() - (25 * 60 * 60)
        os.utime(setup_token, (old, old))

        response = await http.post(
            "/api/setup/redeem-token", json={"token": "old-token"}
        )

        assert response.status_code == 410
        assert setup_token.exists() is False

    async def test_missing_token_is_gone(self, client):
        http, _, _ = client

        response = await http.post(
            "/api/setup/redeem-token", json={"token": "anything"}
        )

        assert response.status_code == 410


class TestBoothEnrollment:
    async def test_code_is_case_insensitive_and_reusable(self, client):
        http, _, enroll_token = client
        enroll_token.write_text("ABCDEF123456", encoding="utf-8")

        first = await http.post(
            "/api/setup/enroll", json={"token": "abcdef123456"}
        )
        second = await http.post(
            "/api/setup/enroll", json={"token": "ABCDEF123456"}
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["internal_api_key"] == "enroll-key"
        assert enroll_token.exists() is True

    async def test_wrong_enrollment_code_rejected(self, client):
        http, _, enroll_token = client
        enroll_token.write_text("ABCDEF123456", encoding="utf-8")

        response = await http.post(
            "/api/setup/enroll", json={"token": "000000000000"}
        )

        assert response.status_code == 401

    async def test_missing_enrollment_token_is_gone(self, client):
        http, _, _ = client

        response = await http.post(
            "/api/setup/enroll", json={"token": "ABCDEF123456"}
        )

        assert response.status_code == 410
