"""Tests for vehicle type routes."""


import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.models.vehicle_type import VehicleType
from api.database import get_db


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """Create a test client with DB override and mocked admin auth."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    from fastapi import Request

    from api.app.middleware.auth import require_admin, require_operator

    async def mock_require_admin(request: Request):
        return {"sub": "1", "username": "admin", "role": "admin"}

    app.dependency_overrides[require_admin] = mock_require_admin
    app.dependency_overrides[require_operator] = mock_require_admin

    # Stub cache invalidation (write hooks) so tests don't hit Redis.
    from unittest.mock import patch
    with patch("api.app.routes.vehicle_types.invalidate_vehicle_types"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def sample_vehicle_type(db_session: AsyncSession) -> VehicleType:
    vt = VehicleType(
        name="Motorcycle",
        code="MOTOR",
        base_tariff=2000,
        hourly_rate=1000,
        max_daily_cap=15000,
    )
    db_session.add(vt)
    await db_session.commit()
    await db_session.refresh(vt)
    return vt


class TestListVehicleTypes:
    async def test_list_empty(self, client: AsyncClient):
        response = await client.get("/api/vehicle-types")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    async def test_list_with_items(self, client: AsyncClient, sample_vehicle_type: VehicleType):
        response = await client.get("/api/vehicle-types")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Motorcycle"
        assert data[0]["code"] == "MOTOR"

    async def test_list_search(self, client: AsyncClient, sample_vehicle_type: VehicleType):
        response = await client.get("/api/vehicle-types?q=Motor")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        response = await client.get("/api/vehicle-types?q=NONEXISTENT")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestCreateVehicleType:
    async def test_create_success(self, client: AsyncClient):
        response = await client.post("/api/vehicle-types", json={
            "name": "Car",
            "code": "MOBIL",
            "base_tariff": 5000,
            "hourly_rate": 2000,
            "max_daily_cap": 30000,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Car"
        assert data["code"] == "MOBIL"
        assert data["base_tariff"] == 5000
        assert "id" in data

    async def test_create_validation_error(self, client: AsyncClient):
        response = await client.post("/api/vehicle-types", json={
            "name": "",
            "code": "",
        })
        assert response.status_code == 422


class TestGetVehicleType:
    async def test_get_by_id(self, client: AsyncClient, sample_vehicle_type: VehicleType):
        response = await client.get(f"/api/vehicle-types/{sample_vehicle_type.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_vehicle_type.id
        assert data["name"] == "Motorcycle"

    async def test_get_not_found(self, client: AsyncClient):
        response = await client.get("/api/vehicle-types/99999")
        assert response.status_code == 404


class TestUpdateVehicleType:
    async def test_update_success(self, client: AsyncClient, sample_vehicle_type: VehicleType):
        response = await client.patch(f"/api/vehicle-types/{sample_vehicle_type.id}", json={
            "name": "Updated Motorcycle",
            "base_tariff": 3000,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Motorcycle"
        assert data["base_tariff"] == 3000
        assert data["code"] == "MOTOR"  # unchanged

    async def test_update_not_found(self, client: AsyncClient):
        response = await client.patch("/api/vehicle-types/99999", json={"name": "X"})
        assert response.status_code == 404


class TestDeleteVehicleType:
    async def test_delete_success(self, client: AsyncClient, sample_vehicle_type: VehicleType):
        response = await client.delete(f"/api/vehicle-types/{sample_vehicle_type.id}")
        assert response.status_code == 200
        data = response.json()
        assert "deleted" in data["message"].lower() or "Vehicle type deleted" in data["message"]

        # Verify it's gone
        response = await client.get(f"/api/vehicle-types/{sample_vehicle_type.id}")
        assert response.status_code == 404

    async def test_delete_not_found(self, client: AsyncClient):
        response = await client.delete("/api/vehicle-types/99999")
        assert response.status_code == 404


class TestVehicleTypeAccess:
    """The POS runs as an operator, so reads are open to it but writes are not."""

    async def test_operator_reads_but_cannot_write(self, db_session: AsyncSession):
        from unittest.mock import AsyncMock, patch

        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        operator = {"sub": "2", "username": "operator", "role": "operator"}
        try:
            with patch("api.app.middleware.auth.require_auth", AsyncMock(return_value=operator)):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    assert (await ac.get("/api/vehicle-types")).status_code == 200
                    denied = await ac.post(
                        "/api/vehicle-types", json={"name": "Truk", "code": "TRK"}
                    )
                    assert denied.status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_user_response_tolerates_stored_email_the_validator_rejects():
    from types import SimpleNamespace

    from api.app.schemas.user import UserResponse

    user = SimpleNamespace(
        id=1, username="agus", email="agus@demo.invalid", full_name="Agus",
        role="operator", is_active=True, phone=None, worker_pin=None,
    )
    assert UserResponse.model_validate(user).email == "agus@demo.invalid"
