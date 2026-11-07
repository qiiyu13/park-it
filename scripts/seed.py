"""Development seed script.

Seeds demo users, gates, shifts, a member and a vehicle type. Never run on a
production install: it refuses to start when APP_ENV=production.

Usage:
    python scripts/seed.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import date, time, timedelta

from sqlalchemy import select

from api.app.models.area_parkir import AreaParkir
from api.app.models.gate import Gate
from api.app.models.member import Member
from api.app.models.shift import Shift
from api.app.models.user import User
from api.app.models.vehicle_type import VehicleType
from api.database import AsyncSessionLocal


def hash_password(password: str) -> str:
    """Hash password using bcrypt directly."""
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()



async def seed() -> None:
    """Seed development data."""
    async with AsyncSessionLocal() as session:
        # Check if already seeded
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            print("Database already seeded. Skipping.")
            return

        print("Seeding development data...")

        # Users
        admin = User(
            username="admin",
            email="admin@eparking.com",
            password_hash=hash_password("admin123"),
            full_name="Administrator",
            role="admin",
            is_active=True,
        )
        operator = User(
            username="operator",
            email="operator@eparking.com",
            password_hash=hash_password("operator123"),
            full_name="Operator Satu",
            role="operator",
            is_active=True,
        )
        session.add_all([admin, operator])
        await session.flush()
        print(f"  Created users: admin (id={admin.id}), operator (id={operator.id})")

        # Vehicle types
        motor = VehicleType(
            name="Motor",
            code="MTR",
            base_tariff=2000,
            hourly_rate=1000,
            max_daily_cap=15000,
            lost_ticket_penalty=20000,
            overnight_mode="midnight",
            overnight_tariff=15000,
            is_progressive=False,
        )
        mobil = VehicleType(
            name="Mobil",
            code="MBL",
            base_tariff=5000,
            hourly_rate=2000,
            max_daily_cap=30000,
            lost_ticket_penalty=50000,
            overnight_mode="midnight",
            overnight_tariff=30000,
            is_progressive=False,
        )
        bus = VehicleType(
            name="Bus",
            code="BUS",
            base_tariff=10000,
            hourly_rate=5000,
            max_daily_cap=60000,
            lost_ticket_penalty=100000,
            overnight_mode="midnight",
            overnight_tariff=60000,
            is_progressive=False,
        )
        session.add_all([motor, mobil, bus])
        await session.flush()
        print("  Created vehicle types: Motor, Mobil, Bus")

        # Area parkir
        area = AreaParkir(
            name="Area Utama",
            code="AU01",
            capacity=100,
            current=0,
            description="Area parkir utama depan",
        )
        session.add(area)
        await session.flush()
        print(f"  Created area: {area.name} (capacity={area.capacity})")

        # Shifts
        shift_pagi = Shift(
            name="Pagi",
            code="PAGI",
            start_time=time(6, 0),
            end_time=time(14, 0),
            is_active=True,
        )
        shift_sore = Shift(
            name="Sore",
            code="SORE",
            start_time=time(14, 0),
            end_time=time(22, 0),
            is_active=True,
        )
        shift_malam = Shift(
            name="Malam",
            code="MALAM",
            start_time=time(22, 0),
            end_time=time(6, 0),
            is_active=True,
        )
        session.add_all([shift_pagi, shift_sore, shift_malam])
        await session.flush()
        print("  Created shifts: Pagi, Sore, Malam")

        # Member
        member = Member(
            card_number="W12345678",
            name="Budi Santoso",
            phone="081234567890",
            email="budi@example.com",
            plate_number="B1234ABC",
            vehicle_type_id=motor.id,
            is_active=True,
            valid_from=date.today() - timedelta(days=30),
            valid_until=date.today() + timedelta(days=335),
            notes="Member test",
        )
        session.add(member)
        await session.flush()
        print(f"  Created member: {member.name} (card={member.card_number})")

        # Gate-in (unified Gate model). Demo controllers default to loopback so a
        # dev seed can never point at real hardware on the LAN.
        gate_in = Gate(
            name="Gate Masuk Utama",
            code="GIN01",
            direction="IN",
            area_parkir_id=area.id,
            protocol="compass",
            controller_host=os.getenv("SEED_GATE_IN_HOST", "127.0.0.1"),
            controller_port=int(os.getenv("SEED_GATE_IN_PORT", "5000")),
            has_close_sensor=True,
            gate_close_duration_ms=5000,
            gate_open_timeout_s=30,
            sensor_stuck_s=300,
            hardware_config={
                "gate_mode": "CASH",
                "emoney_minimum_balance": 10000,
                "print_decision_timeout_seconds": 10,
                "open_command": "TRIG1",
                "pulse_duration_ms": 1000,
                "ticket_printer": {"enabled": True, "printer_name": "Printer-Gate-In"},
                "cameras": [],
                "audio": {"enabled": True, "module": "compass"},
                "led": {"enabled": True, "module": "compass"},
            },
            is_active=True,
            is_online=False,
        )
        session.add(gate_in)
        await session.flush()
        print(f"  Created gate-in: {gate_in.name}")

        # Gate-out (unified Gate model)
        gate_out = Gate(
            name="Gate Keluar Utama",
            code="GOUT01",
            direction="OUT",
            area_parkir_id=area.id,
            protocol="compass",
            controller_host=os.getenv("SEED_GATE_OUT_HOST", "127.0.0.1"),
            controller_port=int(os.getenv("SEED_GATE_OUT_PORT", "5000")),
            has_close_sensor=True,
            gate_close_duration_ms=5000,
            gate_open_timeout_s=30,
            sensor_stuck_s=300,
            hardware_config={
                "payment_timeout_seconds": 120,
                "open_command": "TRIG1",
                "pulse_duration_ms": 1000,
                "receipt_printer": {"enabled": True, "printer_name": "Printer-Gate-Out"},
                "cameras": [],
                "audio": {"enabled": True, "module": "compass"},
                "led": {"enabled": True, "module": "compass"},
            },
            is_active=True,
            is_online=False,
        )
        session.add(gate_out)
        await session.flush()
        print(f"  Created gate-out: {gate_out.name}")

        await session.commit()
        print("\nSeed complete!")
        print("\nLogin credentials:")
        print("  Admin:    admin / admin123")
        print("  Operator: operator / operator123")


if __name__ == "__main__":
    from shared.config import get_settings

    if get_settings().app_env == "production":
        sys.exit("Refusing to seed demo data with APP_ENV=production")
    asyncio.run(seed())
