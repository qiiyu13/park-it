"""Per Pos Keluar report and per-shift report dated by payment day."""

import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.middleware.auth import require_admin
from api.app.models.gate import Gate
from api.app.models.parking_transaction import ParkingTransaction
from api.app.models.shift import Shift
from api.app.models.user import User
from api.database import get_db
from shared.config import get_settings

TZ = ZoneInfo(get_settings().app_timezone)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    mobil = Gate(name="Kasir Mobil", code="GOUT-01", direction="OUT")
    motor = Gate(name="Kasir Motor", code="GOUT-02", direction="OUT")
    kasir = User(username="kasir", full_name="Budi", password_hash="x", role="operator")
    shift = Shift(name="Malam", code="MALAM", start_time=time(22), end_time=time(6))
    db_session.add_all([mobil, motor, kasir, shift])
    await db_session.commit()

    def tx(gate, entry, exit_, fee, method="CASH", status="COMPLETED"):
        return ParkingTransaction(
            barcode=uuid.uuid4().hex[:10], entry_time=entry, exit_time=exit_, fee=fee,
            gate_out_id=gate.id, payment_method=method, status=status,
            operator_id=kasir.id, shift_id=shift.id,
        )

    db_session.add_all([
        tx(mobil, at(25, 23), at(26, 1), 5000),             # in on 25th, paid on 26th
        tx(mobil, at(26, 8), at(26, 9), 3000, "EMONEY"),
        tx(motor, at(26, 8), at(26, 10), 2000),
        tx(mobil, at(26, 8), None, None, None, "ACTIVE"),    # still parked
        tx(mobil, at(24, 8), at(25, 9), 7000),               # paid the day before
    ])
    await db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_admin] = lambda: {"sub": str(kasir.id), "role": "admin"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, mobil
    app.dependency_overrides.clear()


async def test_exit_gate_report_lists_paid_tickets_by_payment_day(client):
    ac, mobil = client
    params = {"date_from": "2026-11-26", "date_to": "2026-11-26"}

    everything = (await ac.get("/api/reports/exit-gate", params=params)).json()
    assert [(i["no"], i["gate_name"], i["fee"]) for i in everything["items"]] == [
        (1, "Kasir Mobil", 5000), (2, "Kasir Mobil", 3000), (3, "Kasir Motor", 2000),
    ]
    assert everything["by_method"] == {"CASH": 7000, "EMONEY": 3000}
    assert (everything["total_amount"], everything["total_count"]) == (10000, 3)
    assert everything["items"][0]["operator_name"] == "Budi"

    one_booth = (
        await ac.get("/api/reports/exit-gate", params={**params, "gate_out_id": mobil.id})
    ).json()
    assert one_booth["total_amount"] == 8000


async def test_shift_report_counts_money_on_payment_day(client):
    ac, _ = client
    report = (
        await ac.get("/api/reports/shift", params={"date_from": "2026-11-26", "date_to": "2026-11-26"})
    ).json()
    # 5.000 (in 25th, out 26th) + 3.000 + 2.000; the 7.000 paid on the 25th is excluded.
    assert report["total_revenue"] == 10000
    assert {i["date"] for i in report["items"]} == {date(2026, 11, 26).isoformat()}
