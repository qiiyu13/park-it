"""Audit wiring and area-occupancy accounting."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.models.area_parkir import AreaParkir
from api.app.models.audit_log import AuditLog
from api.app.models.gate import Gate
from api.app.models.manual_open_log import ManualOpenLog
from api.app.models.user import User
from api.app.services.transaction import (
    complete_exit_transaction,
    create_entry_transaction,
)
from api.app.utils.password import hash_password
from api.database import get_db


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, monkeypatch):
    user = User(
        username=f"admin-{uuid.uuid4().hex[:6]}",
        full_name="Audit Admin",
        password_hash=hash_password("password123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    from api.app.middleware import auth as auth_module

    async def mock_user(request):
        return {
            "sub": str(user.id),
            "username": user.username,
            "role": "admin",
        }

    original_get_current_user = auth_module.get_current_user
    auth_module.get_current_user = mock_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, user

    app.dependency_overrides.clear()
    auth_module.get_current_user = original_get_current_user


class TestGateOpenAudit:
    async def test_manual_open_writes_log_and_audit(self, client, db_session):
        http, user = client
        gate = Gate(
            name="Audit Gate",
            code=f"G-{uuid.uuid4().hex[:6].upper()}",
            direction="IN",
            is_active=True,
        )
        db_session.add(gate)
        await db_session.commit()
        await db_session.refresh(gate)

        with patch(
            "api.app.routes.gates_unified.publish_command", new_callable=AsyncMock
        ) as publish:
            publish.return_value = "1-0"
            response = await http.post(
                f"/api/gates/{gate.id}/open", json={"reason": "unit test"}
            )

        assert response.status_code == 200

        manual = (
            await db_session.execute(
                select(ManualOpenLog).where(ManualOpenLog.gate_id == gate.id)
            )
        ).scalar_one()
        assert manual.opened_by == user.id
        assert manual.reason == "unit test"

        audit = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "GATE_OPEN",
                    AuditLog.entity_id == str(gate.id),
                )
            )
        ).scalar_one()
        assert audit.user_id == user.id


class TestPaymentAudit:
    async def test_cash_payment_writes_audit(self, client, db_session):
        http, user = client
        gate = Gate(
            name="Cash Gate",
            code=f"G-{uuid.uuid4().hex[:6].upper()}",
            direction="OUT",
            is_active=True,
        )
        db_session.add(gate)
        await db_session.commit()
        await db_session.refresh(gate)

        tx = await create_entry_transaction(
            db_session, barcode=f"T{uuid.uuid4().hex[:8]}", payment_method="CASH"
        )
        await db_session.commit()

        with patch(
            "api.app.routes.payments.process_cash_payment", new_callable=AsyncMock
        ) as process:
            process.return_value = {
                "transaction": tx,
                "fee": 5000,
                "change_amount": 5000,
            }
            response = await http.post(
                "/api/payments/cash",
                json={
                    "gate_id": gate.code,
                    "gate_out_id": gate.id,
                    "barcode": tx.barcode,
                    "paid_amount": 10000,
                },
            )

        assert response.status_code == 200
        audit = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "CASH_PAYMENT",
                    AuditLog.entity_id == str(tx.id),
                )
            )
        ).scalar_one()
        assert audit.username == user.username


class TestAreaOccupancy:
    async def test_entry_increments_and_exit_decrements(self, db_session):
        area = AreaParkir(name="Main", code=f"A{uuid.uuid4().hex[:5]}", capacity=10)
        db_session.add(area)
        await db_session.commit()
        await db_session.refresh(area)

        gate = Gate(
            name="Area Gate",
            code=f"G-{uuid.uuid4().hex[:6].upper()}",
            direction="IN",
            area_parkir_id=area.id,
            is_active=True,
        )
        db_session.add(gate)
        await db_session.commit()
        await db_session.refresh(gate)

        tx = await create_entry_transaction(
            db_session,
            barcode=f"T{uuid.uuid4().hex[:8]}",
            gate_in_id=gate.id,
            payment_method="CASH",
        )
        await db_session.commit()
        await db_session.refresh(area)
        assert area.current == 1

        await complete_exit_transaction(
            db_session,
            transaction=tx,
            gate_out_id=gate.id,
            payment_method="CASH",
            fee=1000,
            paid_amount=1000,
        )
        await db_session.commit()
        await db_session.refresh(area)
        assert area.current == 0
