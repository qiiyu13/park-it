"""Lost ticket (karcis hilang): quote, record, pay, receipt, reports."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.middleware.auth import require_admin, require_auth, require_operator
from api.app.models import AuditLog, Gate, LostTicketReport, ParkingTransaction, User, VehicleType
from api.app.routes.lost_tickets import default_entry_time
from api.app.utils.password import hash_password
from api.database import get_db
from workers.critical.print_worker import _build_escpos_receipt

IDENTITY = {"driver_name": "Ferry Prasetio", "id_number": "3578000000000002", "city": "Surabaya"}


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict]] = []

    async def enqueue_job(self, name: str, **kwargs) -> None:
        self.jobs.append((name, kwargs))


@pytest_asyncio.fixture
async def site(db_session: AsyncSession, monkeypatch):
    gate_in = Gate(name="Masuk 1", code=f"GIN-{uuid.uuid4().hex[:4]}", direction="IN")
    gate_out = Gate(
        name="Kasir", code=f"GOUT-{uuid.uuid4().hex[:4]}", direction="OUT",
        hardware_config={"receipt_printer": {"enabled": True}},
    )
    mobil = VehicleType(
        name="Mobil", code=f"M{uuid.uuid4().hex[:4]}", base_tariff=5000, hourly_rate=5000,
        max_daily_cap=0, lost_ticket_penalty=20000, tariff_mode="hourly",
    )
    op = User(username=f"op-{uuid.uuid4().hex[:6]}", full_name="Budi", role="operator",
              password_hash=hash_password("x"))
    db_session.add_all([gate_in, gate_out, mobil, op])
    await db_session.commit()

    arq = FakeArq()

    async def fake_arq():
        return arq

    async def no_snapshots(*args, **kwargs):
        return None

    monkeypatch.setattr("shared.redis.get_arq_redis", fake_arq)
    monkeypatch.setattr("api.app.services.payment.enqueue_snapshots_for_gate", no_snapshots)
    user = {"sub": str(op.id), "role": "admin", "username": op.username}
    app.dependency_overrides[get_db] = lambda: db_session
    for dep in (require_operator, require_auth, require_admin):
        app.dependency_overrides[dep] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db_session, arq, gate_in, gate_out, mobil
    app.dependency_overrides.clear()


async def test_default_entry_is_opening_hour_never_after_now(db_session: AsyncSession):
    tz = ZoneInfo("Asia/Jakarta")
    morning = datetime(2026, 11, 28, 9, 30, tzinfo=tz)
    night = datetime(2026, 11, 28, 2, 0, tzinfo=tz)
    assert (await default_entry_time(db_session, morning)).astimezone(tz) == datetime(
        2026, 11, 28, 6, 0, tzinfo=tz
    )
    assert (await default_entry_time(db_session, night)).astimezone(tz) == datetime(
        2026, 11, 27, 6, 0, tzinfo=tz
    )


async def test_new_lost_ticket_is_paid_with_denda_added(site):
    client, db, arq, gate_in, gate_out, mobil = site
    entry = datetime.now(UTC) - timedelta(hours=2, minutes=30)  # 3 started hours

    quote = (await client.post("/api/lost-tickets/quote", json={
        "plate_number": "h 1234 xy", "vehicle_type_id": mobil.id,
        "entry_time": entry.isoformat(),
    })).json()
    assert (quote["matched"], quote["tariff"], quote["penalty"], quote["total"]) == (
        False, 15000, 20000, 35000
    )

    created = (await client.post("/api/lost-tickets", json={
        "plate_number": "h 1234 xy", "vehicle_type_id": mobil.id, "entry_time": entry.isoformat(),
        "gate_in_id": gate_in.id, "gate_out_id": gate_out.id, **IDENTITY,
    })).json()
    assert created["barcode"] == f"HILANG-{created['resi']}"

    paid = (await client.post("/api/payments/cash", json={
        "gate_id": gate_out.code, "gate_out_id": gate_out.id, "barcode": created["barcode"],
    })).json()
    assert paid["success"] is True and paid["fee"] == 35000

    report = await db.scalar(select(LostTicketReport).where(LostTicketReport.resi == created["resi"]))
    assert (report.plate_number, report.tariff_amount, report.penalty_amount) == ("H1234XY", 15000, 20000)
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "LOST_TICKET"))

    [(name, job)] = [j for j in arq.jobs if j[0] == "print_receipt"]
    receipt = _build_escpos_receipt(job["transaction_data"]).decode(errors="ignore")
    assert "DENDA KARCIS HILANG" in receipt and "Ferry Prasetio" in receipt

    exit_report = (await client.get("/api/reports/exit-gate", params={
        "date_from": str(datetime.now(UTC).date() - timedelta(days=1)),
        "date_to": str(datetime.now(UTC).date() + timedelta(days=1)),
        "gate_out_id": gate_out.id,
    })).json()
    assert (exit_report["total_penalty"], exit_report["total_tariff"]) == (20000, 15000)

    listing = (await client.get("/api/reports/lost-tickets", params={
        "date_from": str(datetime.now(UTC).date() - timedelta(days=1)),
        "date_to": str(datetime.now(UTC).date() + timedelta(days=1)),
    })).json()
    assert [(i["resi"], i["paid"], i["penalty"]) for i in listing["items"]] == [
        (created["resi"], True, 20000)
    ]


async def test_plate_still_parked_reuses_that_ticket(site):
    client, db, _, gate_in, gate_out, mobil = site
    parked = ParkingTransaction(
        barcode="55555", plate_number="H9999AB", gate_in_id=gate_in.id,
        entry_time=datetime.now(UTC) - timedelta(hours=5), status="ACTIVE",
    )
    db.add(parked)
    await db.commit()

    quote = (await client.post("/api/lost-tickets/quote", json={
        "plate_number": "H9999AB", "vehicle_type_id": mobil.id,
    })).json()
    assert quote["matched"] is True and quote["transaction_id"] == parked.id

    created = (await client.post("/api/lost-tickets", json={
        "plate_number": "H9999AB", "vehicle_type_id": mobil.id, "gate_out_id": gate_out.id,
        **IDENTITY,
    })).json()
    assert (created["transaction_id"], created["barcode"]) == (parked.id, "55555")
    await db.refresh(parked)
    assert parked.is_lost_ticket is True
