"""Printer form: gate edits persist and gate_type follows the gate."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.app.main import app
from api.app.middleware.auth import require_admin
from api.app.models.gate import Gate
from api.app.models.printer import Printer
from api.database import get_db


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    db_session.add_all([
        Gate(name="Masuk", code="GIN-01", direction="IN"),
        Gate(name="Keluar", code="GOUT-01", direction="OUT"),
    ])
    await db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_admin] = lambda: {"sub": "1", "role": "admin"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _create(client: AsyncClient, gate_id: str) -> dict:
    response = await client.post(
        "/api/printers/", json={"gate_id": gate_id, "name": "P", "mode": "NETWORK"}
    )
    assert response.status_code == 201
    return response.json()


async def test_create_takes_direction_from_gate(client: AsyncClient):
    assert (await _create(client, "GIN-01"))["gate_type"] == "IN"
    assert (await _create(client, "GOUT-01"))["gate_type"] == "OUT"


async def test_unknown_gate_is_rejected(client: AsyncClient):
    response = await client.post("/api/printers/", json={"gate_id": "NOPE", "name": "P"})
    assert response.status_code == 400


async def test_changing_gate_persists_and_moves_direction(client: AsyncClient):
    printer = await _create(client, "GIN-01")
    response = await client.patch(
        f"/api/printers/{printer['id']}", json={**printer, "gate_id": "GOUT-01"}
    )
    assert response.status_code == 200
    assert (response.json()["gate_id"], response.json()["gate_type"]) == ("GOUT-01", "OUT")


async def test_other_edits_leave_direction_and_orphaned_gate_alone(
    client: AsyncClient, db_session: AsyncSession
):
    printer = Printer(gate_id="DELETED", gate_type="OUT", name="P", mode="NETWORK")
    db_session.add(printer)
    await db_session.commit()
    response = await client.patch(
        f"/api/printers/{printer.id}", json={"gate_id": "DELETED", "name": "Baru"}
    )
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["gate_type"]) == ("Baru", "OUT")


async def test_two_printers_on_one_gate_use_the_oldest(
    client: AsyncClient, db_session: AsyncSession, engine, monkeypatch
):
    for ip in ("10.0.0.1", "10.0.0.2"):
        db_session.add(
            Printer(gate_id="GIN-01", gate_type="IN", name=ip, mode="NETWORK", ip_address=ip)
        )
        await db_session.commit()

    from workers.critical.print_worker import _get_print_config

    monkeypatch.setattr("api.database.AsyncSessionLocal", async_sessionmaker(engine))
    config = await _get_print_config("GIN-01", gate_type="IN")
    assert config["printer_ip_address"] == "10.0.0.1"
