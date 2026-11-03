"""Event-consumer business handlers (ticket entry, RFID entry/exit warnings)."""

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.gate import Gate
from api.app.models.member import Member
from api.app.models.parking_transaction import ParkingTransaction
from api.app.services.event_consumer import EventConsumer
from shared.config import get_settings
from shared.events import (
    DisplayTextCommand,
    OpenGateCommand,
    PlayAudioCommand,
    PrintTicketThenOpenCommand,
)


def _local_today() -> date:
    return datetime.now(ZoneInfo(get_settings().app_timezone)).date()


class _SessionCtx:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *exc) -> None:
        return None


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr("api.database.AsyncSessionLocal", lambda: _SessionCtx(db_session))
    yield


async def _gate(db: AsyncSession, direction: str = "IN") -> Gate:
    gate = Gate(
        name=f"Gate {direction}",
        code=f"{direction}-{uuid.uuid4().hex[:8].upper()}",
        direction=direction,
        is_active=True,
        hardware_config={},
    )
    db.add(gate)
    await db.commit()
    await db.refresh(gate)
    return gate


class TestTicketButton:
    async def test_creates_cash_transaction_and_prints(
        self, db_session: AsyncSession, monkeypatch
    ):
        gate = await _gate(db_session)
        publish = AsyncMock()
        monkeypatch.setattr(
            "api.app.services.gate_command.publish_command", publish
        )

        consumer = EventConsumer()
        await consumer._handle_ticket_button_pressed({"gate_id": gate.code})

        tx = (
            await db_session.execute(
                select(ParkingTransaction).where(
                    ParkingTransaction.gate_in_id == gate.id
                )
            )
        ).scalar_one()
        assert tx.status == "ACTIVE"
        assert tx.payment_method == "CASH"
        assert tx.barcode

        publish.assert_awaited_once()
        command = publish.await_args.args[0]
        assert isinstance(command, PrintTicketThenOpenCommand)
        assert command.gate_id == gate.code
        assert command.barcode == tx.barcode


class TestRfidEntry:
    async def _member(
        self, db: AsyncSession, *, valid_days: int
    ) -> Member:
        member = Member(
            card_number=f"CARD-{id(db)}",
            name="Member",
            is_active=True,
            valid_until=_local_today() + timedelta(days=valid_days),
        )
        db.add(member)
        await db.commit()
        await db.refresh(member)
        return member

    async def test_valid_member_creates_transaction_and_opens(
        self, db_session: AsyncSession, monkeypatch
    ):
        gate = await _gate(db_session)
        member = await self._member(db_session, valid_days=30)
        publish = AsyncMock()
        monkeypatch.setattr(
            "api.app.services.gate_command.publish_command", publish
        )

        consumer = EventConsumer()
        await consumer._handle_rfid_card_read(
            {"gate_id": gate.code, "card_number": member.card_number}
        )

        tx = (
            await db_session.execute(
                select(ParkingTransaction).where(
                    ParkingTransaction.card_number == member.card_number
                )
            )
        ).scalar_one()
        assert tx.member_id == member.id
        assert tx.payment_method == "RFID_MEMBER"

        command = publish.await_args.args[0]
        assert isinstance(command, OpenGateCommand)
        assert command.gate_id == gate.code

    async def test_expiry_warning_does_not_block_consumer(
        self, db_session: AsyncSession, monkeypatch
    ):
        gate = await _gate(db_session)
        member = await self._member(db_session, valid_days=1)
        publish = AsyncMock()
        monkeypatch.setattr(
            "api.app.services.gate_command.publish_command", publish
        )

        consumer = EventConsumer()
        await consumer._handle_rfid_card_read(
            {"gate_id": gate.code, "card_number": member.card_number}
        )

        command_types = [
            type(call.args[0]) for call in publish.await_args_list
        ]
        assert DisplayTextCommand in command_types
        assert PlayAudioCommand in command_types
        assert OpenGateCommand in command_types

    async def test_unknown_card_is_rejected(self, db_session: AsyncSession, monkeypatch):
        gate = await _gate(db_session)
        publish = AsyncMock()
        monkeypatch.setattr(
            "api.app.services.gate_command.publish_command", publish
        )

        consumer = EventConsumer()
        await consumer._handle_rfid_card_read(
            {"gate_id": gate.code, "card_number": "NOPE"}
        )

        from shared.events import RejectCardCommand

        command = publish.await_args.args[0]
        assert isinstance(command, RejectCardCommand)
        assert "Terdaftar" in command.line2
