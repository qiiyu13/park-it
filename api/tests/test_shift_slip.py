"""Shift close: takings per session, printed slip, POS cash counter."""

import re
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.main import app
from api.app.middleware.auth import require_auth, require_operator
from api.app.models.gate import Gate
from api.app.models.parking_transaction import ParkingTransaction
from api.app.models.shift import Shift
from api.app.models.user import User
from api.app.services import worker_session as svc
from api.app.utils.password import hash_password
from api.database import get_db
from workers.critical.print_worker import _build_escpos_shift_slip, terbilang

PIN = "1234"


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict]] = []

    async def enqueue_job(self, name: str, **kwargs) -> None:
        self.jobs.append((name, kwargs))


@pytest_asyncio.fixture
async def site(db_session: AsyncSession, monkeypatch):
    gate = Gate(
        name="Kasir Mobil", code="GOUT-01", direction="OUT",
        hardware_config={"receipt_printer": {"enabled": True}},
    )
    other_gate = Gate(name="Kasir Motor", code="GOUT-02", direction="OUT")
    worker = User(
        username=f"w-{uuid.uuid4().hex[:6]}", full_name="Budi", role="operator",
        password_hash=hash_password("x"), worker_pin=hash_password(PIN),
    )
    shift = Shift(name="Pagi", code="PAGI", start_time=time(0), end_time=time(23, 59, 59))
    db_session.add_all([gate, other_gate, worker, shift])
    await db_session.commit()

    session = await svc.check_in(db_session, gate_id=gate.id, worker_id=worker.id, pin=PIN)
    session.started_at = datetime.now(UTC) - timedelta(hours=2)
    now = datetime.now(UTC)

    def tx(method, fee, paid=None, *, gate_out=gate, exit_time=now - timedelta(minutes=30),
           status="COMPLETED"):
        return ParkingTransaction(
            barcode=uuid.uuid4().hex[:10], entry_time=exit_time - timedelta(hours=1),
            exit_time=exit_time, gate_out_id=gate_out.id, payment_method=method,
            fee=fee, paid_amount=paid if paid is not None else fee, status=status,
            operator_id=worker.id,
        )

    db_session.add_all([
        tx("CASH", 5000, paid=10000),        # driver paid 10.000, got 5.000 change
        tx("CASH", 3000),
        tx("EMONEY", 4000),
        tx("CASH", 9999, exit_time=now - timedelta(hours=3)),  # before check-in
        tx("CASH", 9999, gate_out=other_gate),                 # other booth
        tx("CASH", 9999, status="ACTIVE"),                      # not paid
    ])
    await db_session.commit()

    arq = FakeArq()

    async def fake_arq():
        return arq

    monkeypatch.setattr("shared.redis.get_arq_redis", fake_arq)
    user = {"sub": str(worker.id), "role": "operator"}
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_operator] = lambda: user
    app.dependency_overrides[require_auth] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session, arq
    app.dependency_overrides.clear()


async def test_summary_counts_fee_for_this_booth_and_window(site):
    client, session, _ = site
    data = (await client.get(f"/api/worker-sessions/{session.id}/summary")).json()

    assert data["by_method"] == {
        "CASH": {"count": 2, "amount": 8000},
        "EMONEY": {"count": 1, "amount": 4000},
    }
    assert (data["cash_amount"], data["total_amount"], data["total_count"]) == (8000, 12000, 3)
    assert (data["worker_name"], data["gate_code"], data["shift_name"]) == ("Budi", "GOUT-01", "Pagi")


async def test_handover_prints_one_slip(site):
    client, session, arq = site
    response = await client.post(
        f"/api/worker-sessions/{session.id}/confirm-outgoing", json={"pin": PIN}
    )
    assert response.status_code == 200
    assert [(name, kw["gate_id"], kw["summary"]["cash_amount"]) for name, kw in arq.jobs] == [
        ("print_shift_slip", "GOUT-01", 8000)
    ]

    # Force-leave after the outgoing step must not print a second slip.
    response = await client.post(
        f"/api/worker-sessions/{session.id}/force-leave", json={"pin": PIN, "reason": "sakit"}
    )
    assert response.status_code == 200
    assert len(arq.jobs) == 1


async def test_force_leave_from_active_prints_slip(site):
    client, session, arq = site
    response = await client.post(
        f"/api/worker-sessions/{session.id}/force-leave", json={"pin": PIN, "reason": "sakit"}
    )
    assert response.status_code == 200
    assert [name for name, _ in arq.jobs] == ["print_shift_slip"]


async def test_pos_cash_counter_excludes_change(site):
    client, _, _ = site
    data = (await client.get("/api/pos/shift-summary")).json()
    # Counter is per login user per day: 5.000 + 3.000 plus the three 9.999 rows.
    # Summing paid_amount instead would add the 5.000 change.
    assert data["cash_collected"] == 5000 + 3000 + 3 * 9999


def test_terbilang_and_slip():
    assert terbilang(798000) == "tujuh ratus sembilan puluh delapan ribu"
    assert terbilang(1250500) == "satu juta dua ratus lima puluh ribu lima ratus"
    assert terbilang(11) == "sebelas" and terbilang(115) == "seratus lima belas"
    slip = _build_escpos_shift_slip({
        "worker_name": "Budi", "gate_code": "GOUT-01", "gate_name": "Kasir Mobil",
        "by_method": {"CASH": {"count": 2, "amount": 8000}}, "cash_amount": 8000,
        "total_amount": 8000, "total_count": 2,
        "started_at": "2026-11-26T07:00:00+07:00", "closed_at": "2026-11-26T15:00:00+07:00",
    }).decode("latin1")
    assert "## delapan ribu rupiah ##" in slip
    assert "Rp. 8.000,-" in slip and "(Budi)" in slip
    printable = re.sub(r"\x1b[@]|\x1bE.|\x1d...", "", slip)
    assert all(len(line) <= 48 for line in printable.split("\n"))
