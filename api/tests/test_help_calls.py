"""Help button at an entry gate reaches the exit POS until handled."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.app.main import app
from api.app.middleware.auth import require_auth
from api.app.models.gate import Gate
from api.app.models.operator_alert import OperatorAlert
from api.app.models.user import User
from api.app.services.event_consumer import EventConsumer
from api.database import get_db


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, engine, monkeypatch):
    operator = User(username="kasir", password_hash="x", role="operator")
    db_session.add_all([Gate(name="Masuk Mobil 1", code="GIN-01", direction="IN"), operator])
    await db_session.commit()
    monkeypatch.setattr("api.database.AsyncSessionLocal", async_sessionmaker(engine))
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_auth] = lambda: {"sub": str(operator.id), "role": "operator"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _press(gate_code: str = "GIN-01") -> None:
    await EventConsumer()._handle_message(
        f"parking.events.{gate_code}",
        f'{{"event_type": "help_button_pressed", "gate_id": "{gate_code}"}}',
    )


async def test_press_shows_one_call_until_handled(client: AsyncClient, db_session: AsyncSession):
    operator_id = (await db_session.execute(select(User.id))).scalar_one()
    await _press()
    await _press()  # repeat press while open adds nothing

    calls = (await client.get("/api/operator-alerts/help")).json()
    assert [(c["gate_code"], c["gate_name"]) for c in calls] == [("GIN-01", "Masuk Mobil 1")]

    response = await client.post(f"/api/operator-alerts/{calls[0]['id']}/resolve")
    assert response.status_code == 200
    assert (await client.get("/api/operator-alerts/help")).json() == []

    alert = await db_session.get(OperatorAlert, calls[0]["id"])
    await db_session.refresh(alert)
    assert (alert.is_resolved, alert.resolved_by) == (True, operator_id)

    await _press()  # a new press after handling opens a new call
    assert len((await client.get("/api/operator-alerts/help")).json()) == 1


async def test_unknown_gate_and_other_alerts_are_ignored(
    client: AsyncClient, db_session: AsyncSession
):
    await _press("NOPE")
    other = OperatorAlert(gate_type="out", gate_id=1, alert_type="TIMEOUT", message="x")
    db_session.add(other)
    await db_session.commit()

    assert (await client.get("/api/operator-alerts/help")).json() == []
    assert (await client.post(f"/api/operator-alerts/{other.id}/resolve")).status_code == 404
    assert (await client.post("/api/operator-alerts/99999/resolve")).status_code == 404
    rows = (await db_session.execute(select(OperatorAlert))).scalars().all()
    assert [r.alert_type for r in rows] == ["TIMEOUT"]
