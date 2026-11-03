"""One-shot provisioning used by the technician Quick Install path.

This is the v1-style "run one command and start using the UI" experience,
implemented safely:

* every step is an upsert keyed by a unique column (username/code), so a
  re-run never truncates or overwrites live data;
* no hardware credentials or tariff values are invented silently — the
  defaults are explicit, returned to the installer, and written to the
  install summary;
* the admin password is either supplied by the installer or generated once
  and returned to the caller (the CLI writes it to a 0600 notes file).

The interactive setup wizard remains available for non-standard sites.
"""

from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.area_parkir import AreaParkir
from api.app.models.gate import Gate
from api.app.models.site_config import SiteConfig
from api.app.models.user import User
from api.app.models.vehicle_type import VehicleType
from api.app.services.setup import delete_setup_token as _delete_setup_token
from api.app.services.setup import mark_setup_complete
from api.app.utils.password import hash_password
from shared.logging import get_logger

logger = get_logger("quickstart")

TARIFF_PRESETS: dict[str, list[dict[str, Any]]] = {
    "standard": [
        {"name": "Motor", "code": "MOTOR", "hourly_rate": 2000, "max_daily_cap": 15000},
        {"name": "Mobil", "code": "MOBIL", "hourly_rate": 5000, "max_daily_cap": 50000},
        {"name": "Bus / Truk", "code": "BUS", "hourly_rate": 10000, "max_daily_cap": 100000},
    ],
    "mall": [
        {
            "name": "Motor",
            "code": "MOTOR",
            "base_tariff": 2000,
            "hourly_rate": 1000,
            "max_daily_cap": 15000,
            "is_progressive": True,
        },
        {
            "name": "Mobil",
            "code": "MOBIL",
            "base_tariff": 5000,
            "hourly_rate": 2000,
            "max_daily_cap": 30000,
            "is_progressive": True,
        },
        {
            "name": "Truk",
            "code": "TRUK",
            "base_tariff": 10000,
            "hourly_rate": 3000,
            "max_daily_cap": 60000,
            "is_progressive": True,
        },
    ],
}


@dataclass
class QuickstartResult:
    """Everything the installer needs to print the hand-over summary."""

    admin_username: str
    admin_created: bool
    admin_password: str | None = None
    site_created: bool = False
    vehicle_types_created: list[str] = field(default_factory=list)
    area_created: bool = False
    gates_created: list[dict[str, Any]] = field(default_factory=list)
    gates_existing: list[str] = field(default_factory=list)
    tariff_preset: str = "standard"
    tariff_items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admin_username": self.admin_username,
            "admin_created": self.admin_created,
            "admin_password": self.admin_password,
            "site_created": self.site_created,
            "vehicle_types_created": self.vehicle_types_created,
            "area_created": self.area_created,
            "gates_created": self.gates_created,
            "gates_existing": self.gates_existing,
            "tariff_preset": self.tariff_preset,
            "tariff_items": self.tariff_items,
        }


def _gate_codes(direction: str, count: int) -> list[str]:
    prefix = "GIN" if direction == "IN" else "GOUT"
    return [f"{prefix}-{n + 1:02d}" for n in range(count)]


def _next_gate_ip(base_ip: str, offset: int) -> str:
    address = ipaddress.IPv4Address(base_ip)
    return str(address + offset)


async def provision_quickstart(
    db: AsyncSession,
    *,
    admin_username: str = "admin",
    admin_password: str | None = None,
    admin_full_name: str = "Administrator",
    admin_email: str | None = None,
    site_name: str = "E-Parking",
    site_address: str | None = None,
    site_city: str | None = None,
    tariff_preset: str = "standard",
    in_count: int = 1,
    out_count: int = 1,
    area_name: str = "Area Utama",
    area_code: str = "MAIN",
    area_capacity: int = 100,
    gate_base_ip: str = "192.168.1.100",
    gate_port: int = 5000,
    complete_setup: bool = True,
    delete_setup_token: bool = True,
) -> QuickstartResult:
    """Provision a usable site without the interactive wizard.

    Raises:
        ValueError: for invalid counts/preset/password/base IP.
    """
    if not 0 <= in_count <= 8 or not 0 <= out_count <= 8:
        raise ValueError("gate counts must be between 0 and 8")
    if in_count + out_count == 0:
        raise ValueError("at least one gate is required")
    preset = TARIFF_PRESETS.get(tariff_preset)
    if preset is None:
        raise ValueError(
            f"unknown tariff preset '{tariff_preset}' (choose from {', '.join(TARIFF_PRESETS)})"
        )
    if admin_password is not None and len(admin_password) < 8:
        raise ValueError("admin password must be at least 8 characters")
    try:
        ipaddress.IPv4Address(gate_base_ip)
    except ValueError as exc:
        raise ValueError(f"invalid gate base IP: {gate_base_ip}") from exc

    result = QuickstartResult(
        admin_username=admin_username,
        admin_created=False,
        tariff_preset=tariff_preset,
        tariff_items=preset,
    )

    # ── Admin ────────────────────────────────────────────────────────────
    admin_count = await db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin")
    )
    if (admin_count or 0) == 0:
        result.admin_password = admin_password or secrets.token_hex(6)
        db.add(
            User(
                username=admin_username,
                email=admin_email,
                full_name=admin_full_name,
                password_hash=hash_password(result.admin_password),
                role="admin",
                is_active=True,
            )
        )
        result.admin_created = True

    # ── Site config (singleton) ──────────────────────────────────────────
    site = (await db.execute(select(SiteConfig).limit(1))).scalar_one_or_none()
    if site is None:
        db.add(
            SiteConfig(
                name=site_name,
                address=site_address,
                city=site_city,
            )
        )
        result.site_created = True

    # ── Vehicle types ────────────────────────────────────────────────────
    existing_codes = set(
        (await db.execute(select(VehicleType.code))).scalars().all()
    )
    for item in preset:
        if item["code"] in existing_codes:
            continue
        db.add(
            VehicleType(
                name=item["name"],
                code=item["code"],
                base_tariff=int(item.get("base_tariff", 0)),
                hourly_rate=int(item.get("hourly_rate", 0)),
                max_daily_cap=int(item.get("max_daily_cap", 0)),
                lost_ticket_penalty=int(item.get("lost_ticket_penalty", 0)),
                overnight_mode=str(item.get("overnight_mode", "midnight")),
                overnight_tariff=int(item.get("overnight_tariff", 0)),
                is_progressive=bool(item.get("is_progressive", False)),
            )
        )
        existing_codes.add(item["code"])
        result.vehicle_types_created.append(item["code"])

    # ── Area ─────────────────────────────────────────────────────────────
    area_exists = await db.scalar(
        select(AreaParkir.id).where(AreaParkir.code == area_code)
    )
    if area_exists is None:
        db.add(
            AreaParkir(
                name=area_name,
                code=area_code,
                capacity=area_capacity,
                current=0,
            )
        )
        result.area_created = True

    # ── Gates ────────────────────────────────────────────────────────────
    existing_gate_codes = set(
        (await db.execute(select(Gate.code))).scalars().all()
    )
    for direction, count in (("IN", in_count), ("OUT", out_count)):
        for offset, code in enumerate(_gate_codes(direction, count)):
            if code in existing_gate_codes:
                result.gates_existing.append(code)
                continue
            # Entry controllers are TCP Compass by default, matching the
            # wizard's .100/.101 prefill. Exit lanes are booth-driven; their
            # controller is configured in Device after the booth is enrolled.
            is_entry = direction == "IN"
            gate = Gate(
                name=("Pintu Masuk" if is_entry else "Pintu Keluar") + f" {offset + 1}",
                code=code,
                direction=direction,
                protocol="compass",
                controller_host=(
                    _next_gate_ip(gate_base_ip, offset) if is_entry else None
                ),
                controller_port=gate_port if is_entry else None,
                hardware_config={},
            )
            db.add(gate)
            existing_gate_codes.add(code)
            result.gates_created.append(
                {
                    "code": code,
                    "direction": direction,
                    "controller": (
                        f"{gate.controller_host}:{gate_port}" if is_entry else None
                    ),
                }
            )

    await db.commit()

    if complete_setup:
        await mark_setup_complete(db, complete=True)
    if delete_setup_token:
        _delete_setup_token()

    logger.info(
        "quickstart_provisioned",
        admin_created=result.admin_created,
        vehicle_types=result.vehicle_types_created,
        gates=len(result.gates_created),
        tariff_preset=tariff_preset,
    )
    return result
