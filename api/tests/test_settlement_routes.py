import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.database import get_db


@pytest.fixture
async def client(db_session: AsyncSession):
    """Create a test client with DB override."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    from api.app.middleware import auth as auth_module
    original_get_current_user = auth_module.get_current_user

    async def mock_get_current_user(request):
        return {"sub": "1", "username": "admin", "role": "admin"}

    auth_module.get_current_user = mock_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    auth_module.get_current_user = original_get_current_user


class TestSettlements:
    async def test_list_settlements_empty(self, client: AsyncClient):
        response = await client.get("/api/settlements")
        assert response.status_code == 200
        assert response.json() == []

    async def test_trigger_settlement(self, client: AsyncClient):
        from unittest.mock import AsyncMock, MagicMock, patch

        arq = MagicMock()
        arq.enqueue_job = AsyncMock()
        with patch("shared.redis.get_arq_redis", new=AsyncMock(return_value=arq)):
            response = await client.post("/api/settlements/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        arq.enqueue_job.assert_awaited_once()
        assert arq.enqueue_job.await_args.args[0] == "generate_settlement_file"

    async def test_trigger_settlement_queue_unavailable(self, client: AsyncClient):
        from unittest.mock import AsyncMock, patch

        with patch(
            "shared.redis.get_arq_redis",
            new=AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            response = await client.post("/api/settlements/trigger")

        assert response.status_code == 503
