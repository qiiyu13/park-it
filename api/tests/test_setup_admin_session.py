"""Tests for the setup-session → admin JWT hand-off."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.services.quickstart import provision_quickstart
from api.app.services.setup import create_session
from api.database import get_db


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestSetupAdminSession:
    async def test_issues_admin_cookie_for_valid_setup_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await provision_quickstart(
            db_session,
            admin_username="resume-admin",
            delete_setup_token=False,
        )
        session = await create_session(db_session)

        client.cookies.set("parking_setup_session", session.session_token)
        response = await client.post("/api/setup/admin-session")
        client.cookies.clear()

        assert response.status_code == 200
        assert response.json()["username"] == "resume-admin"
        set_cookie = " ".join(response.headers.get_list("set-cookie"))
        assert "access_token=" in set_cookie
        assert "refresh_token=" in set_cookie

    async def test_rejects_without_setup_session(self, client: AsyncClient):
        response = await client.post("/api/setup/admin-session")
        assert response.status_code == 401

    async def test_rejects_when_no_admin_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await create_session(db_session)
        client.cookies.set("parking_setup_session", session.session_token)
        response = await client.post("/api/setup/admin-session")
        client.cookies.clear()
        assert response.status_code == 409
