"""Payment idempotency: retried POS requests must not double-charge."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.services.transaction import create_entry_transaction
from api.database import get_db


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def connect(self) -> None:
        return None

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    from api.app.middleware import auth as auth_module

    original = auth_module.get_current_user

    async def mock_user(request):
        return {"sub": "1", "username": "operator", "role": "operator"}

    auth_module.get_current_user = mock_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    auth_module.get_current_user = original


class TestCashIdempotency:
    async def test_same_key_returns_cached_response_and_processes_once(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        tx = await create_entry_transaction(
            db_session,
            barcode=f"T{uuid.uuid4().hex[:8]}",
            payment_method="CASH",
        )
        await db_session.commit()

        fake = _FakeRedis()
        with patch("api.app.routes.payments.redis_client", fake), patch(
            "api.app.routes.payments.process_cash_payment", new_callable=AsyncMock
        ) as process:
            process.return_value = {
                "transaction": tx,
                "fee": 5000,
                "change_amount": 5000,
            }
            headers = {"X-Idempotency-Key": "pos-retry-1"}
            first = await client.post(
                "/api/payments/cash",
                json={
                    "gate_id": "GOUT-01",
                    "gate_out_id": 1,
                    "barcode": tx.barcode,
                    "paid_amount": 10000,
                },
                headers=headers,
            )
            second = await client.post(
                "/api/payments/cash",
                json={
                    "gate_id": "GOUT-01",
                    "gate_out_id": 1,
                    "barcode": tx.barcode,
                    "paid_amount": 10000,
                },
                headers=headers,
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        process.assert_awaited_once()
        cached = json.loads(fake.values["idempotency:pos-retry-1"])
        assert cached["success"] is True
        assert cached["payment_method"] == "CASH"

    async def test_different_keys_process_separately(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        tx = await create_entry_transaction(
            db_session,
            barcode=f"T{uuid.uuid4().hex[:8]}",
            payment_method="CASH",
        )
        await db_session.commit()

        with patch("api.app.routes.payments.redis_client", _FakeRedis()), patch(
            "api.app.routes.payments.process_cash_payment", new_callable=AsyncMock
        ) as process:
            process.return_value = {
                "transaction": tx,
                "fee": 5000,
                "change_amount": 0,
            }
            for key in ("key-a", "key-b"):
                response = await client.post(
                    "/api/payments/cash",
                    json={
                        "gate_id": "GOUT-01",
                        "gate_out_id": 1,
                        "barcode": tx.barcode,
                        "paid_amount": 5000,
                    },
                    headers={"X-Idempotency-Key": key},
                )
                assert response.status_code == 200

        assert process.await_count == 2
