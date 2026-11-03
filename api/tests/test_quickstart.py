"""Tests for the Quick Install provisioning service."""

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.area_parkir import AreaParkir
from api.app.models.gate import Gate
from api.app.models.site_config import SiteConfig
from api.app.models.user import User
from api.app.models.vehicle_type import VehicleType
from api.app.services.quickstart import provision_quickstart
from api.app.services.setup import setup_complete


class TestQuickstartProvision:
    async def test_creates_usable_site(self, db_session: AsyncSession):
        result = await provision_quickstart(
            db_session,
            site_name="Parkir Test",
            delete_setup_token=False,
        )

        assert result.admin_created is True
        assert result.admin_password
        assert len(result.admin_password) >= 8
        assert result.site_created is True
        assert set(result.vehicle_types_created) == {"MOTOR", "MOBIL", "BUS"}
        assert result.area_created is True
        assert [g["code"] for g in result.gates_created] == ["GIN-01", "GOUT-01"]
        assert result.gates_created[0]["controller"] == "192.168.1.100:5000"
        assert result.gates_created[1]["controller"] is None
        assert await setup_complete(db_session) is True

        admin = (
            await db_session.execute(select(User).where(User.role == "admin"))
        ).scalar_one()
        assert admin.username == "admin"
        site = (await db_session.execute(select(SiteConfig))).scalar_one()
        assert site.name == "Parkir Test"

    async def test_rerun_is_idempotent(self, db_session: AsyncSession):
        first = await provision_quickstart(db_session, delete_setup_token=False)
        second = await provision_quickstart(db_session, delete_setup_token=False)

        assert first.admin_created is True
        assert second.admin_created is False
        assert second.admin_password is None
        assert second.gates_created == []
        assert set(second.gates_existing) == {"GIN-01", "GOUT-01"}

        counts = {
            "users": await db_session.scalar(
                select(func.count()).select_from(User).where(User.role == "admin")
            ),
            "gates": await db_session.scalar(select(func.count()).select_from(Gate)),
            "vehicle_types": await db_session.scalar(
                select(func.count()).select_from(VehicleType)
            ),
            "areas": await db_session.scalar(select(func.count()).select_from(AreaParkir)),
        }
        assert counts == {
            "users": 1,
            "gates": 2,
            "vehicle_types": 3,
            "areas": 1,
        }

    async def test_custom_topology_and_tariff(self, db_session: AsyncSession):
        result = await provision_quickstart(
            db_session,
            tariff_preset="mall",
            in_count=2,
            out_count=1,
            gate_base_ip="10.0.0.50",
            delete_setup_token=False,
        )

        assert [g["code"] for g in result.gates_created] == [
            "GIN-01",
            "GIN-02",
            "GOUT-01",
        ]
        assert result.gates_created[0]["controller"] == "10.0.0.50:5000"
        assert result.gates_created[1]["controller"] == "10.0.0.51:5000"
        assert set(result.vehicle_types_created) == {"MOTOR", "MOBIL", "TRUK"}

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"in_count": 0, "out_count": 0}, "at least one gate"),
            ({"tariff_preset": "nope"}, "unknown tariff preset"),
            ({"admin_password": "short"}, "at least 8"),
            ({"gate_base_ip": "999.1.1.1"}, "invalid gate base IP"),
        ],
    )
    async def test_rejects_invalid_input(self, db_session: AsyncSession, kwargs, message):
        with pytest.raises(ValueError, match=message):
            await provision_quickstart(db_session, delete_setup_token=False, **kwargs)


@pytest_asyncio.fixture(autouse=True)
async def _clean_setup_token(monkeypatch):
    """Never touch /etc/parking during tests, even if a caller forgets."""
    import api.app.services.quickstart as qs

    monkeypatch.setattr(qs, "_delete_setup_token", lambda: None, raising=False)
    yield
