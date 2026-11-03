"""Worker session lifecycle: check-in, handover, takeover, force-leave."""

import uuid
from datetime import UTC, date, datetime, time

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.gate import Gate
from api.app.models.operator_alert import OperatorAlert
from api.app.models.shift import Shift
from api.app.models.shift_assignment import ShiftAssignment
from api.app.models.user import User
from api.app.services import worker_session as svc
from api.app.utils.password import hash_password

PIN = "1234"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


async def _worker(db: AsyncSession, *, pin: str | None = PIN) -> User:
    user = User(
        username=_unique("worker"),
        full_name="Test Worker",
        password_hash=hash_password("login-password"),
        worker_pin=hash_password(pin) if pin else None,
        role="operator",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _gate(db: AsyncSession) -> Gate:
    gate = Gate(
        name="Test Gate",
        code=_unique("GIN").upper(),
        direction="IN",
        is_active=True,
    )
    db.add(gate)
    await db.commit()
    await db.refresh(gate)
    return gate


async def _shift(db: AsyncSession) -> Shift:
    shift = Shift(
        name="All day",
        code=_unique("SHIFT").upper(),
        start_time=time(0, 0),
        end_time=time(23, 59, 59),
        is_active=True,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


async def _check_in(db: AsyncSession, gate: Gate, worker: User, **kwargs):
    """Check in, creating the all-day shift row if the test didn't."""
    if await db.scalar(select(Shift.id).limit(1)) is None:
        await _shift(db)
    return await svc.check_in(
        db, gate_id=gate.id, worker_id=worker.id, pin=kwargs.pop("pin", PIN), **kwargs
    )


async def _assignment(
    db: AsyncSession, *, shift: Shift, worker: User, gate: Gate
) -> ShiftAssignment:
    assignment = ShiftAssignment(
        shift_id=shift.id,
        worker_id=worker.id,
        gate_id=gate.id,
        date=datetime.now(UTC).date(),
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


class TestCheckIn:
    async def test_check_in_with_assignment(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        gate = await _gate(db_session)
        shift = await _shift(db_session)
        assignment = await _assignment(
            db_session, shift=shift, worker=worker, gate=gate
        )

        session = await svc.check_in(
            db_session,
            gate_id=gate.id,
            worker_id=worker.id,
            pin=PIN,
            shift_assignment_id=assignment.id,
        )

        assert session.status == "ACTIVE"
        assert session.worker_id == worker.id
        assert session.gate_id == gate.id
        assert session.shift_id == shift.id
        assert session.date == date.today() or session.date == datetime.now(UTC).date()

    async def test_substitute_check_in_does_not_crash(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        original = await _worker(db_session)
        gate = await _gate(db_session)
        shift = await _shift(db_session)

        # WorkerSession has no original_worker_id column; this used to raise a
        # SQLAlchemy TypeError before the session was even added.
        session = await svc.check_in(
            db_session,
            gate_id=gate.id,
            worker_id=worker.id,
            pin=PIN,
            is_substitute=True,
            original_worker_id=original.id,
        )
        assert session.status == "ACTIVE"
        assert session.is_substitute is True

    async def test_wrong_pin_rejected(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        gate = await _gate(db_session)

        with pytest.raises(HTTPException) as exc:
            await svc.check_in(
                db_session, gate_id=gate.id, worker_id=worker.id, pin="9999"
            )
        assert exc.value.status_code == 401

    async def test_worker_without_pin_rejected(self, db_session: AsyncSession):
        worker = await _worker(db_session, pin=None)
        gate = await _gate(db_session)

        with pytest.raises(HTTPException) as exc:
            await svc.check_in(
                db_session, gate_id=gate.id, worker_id=worker.id, pin=PIN
            )
        assert exc.value.status_code == 400

    async def test_assignment_for_another_gate_rejected(
        self, db_session: AsyncSession
    ):
        worker = await _worker(db_session)
        gate = await _gate(db_session)
        other_gate = await _gate(db_session)
        shift = await _shift(db_session)
        assignment = await _assignment(
            db_session, shift=shift, worker=worker, gate=other_gate
        )

        with pytest.raises(HTTPException) as exc:
            await svc.check_in(
                db_session,
                gate_id=gate.id,
                worker_id=worker.id,
                pin=PIN,
                shift_assignment_id=assignment.id,
            )
        assert exc.value.status_code == 400

    async def test_second_active_session_rejected(self, db_session: AsyncSession):
        first = await _worker(db_session)
        second = await _worker(db_session)
        gate = await _gate(db_session)

        await _check_in(db_session, gate, first)
        with pytest.raises(HTTPException) as exc:
            await svc.check_in(
                db_session, gate_id=gate.id, worker_id=second.id, pin=PIN
            )
        assert exc.value.status_code == 409


class TestHandover:
    async def test_outgoing_then_incoming(self, db_session: AsyncSession):
        outgoing = await _worker(db_session)
        incoming = await _worker(db_session)
        gate = await _gate(db_session)

        session = await _check_in(db_session, gate, outgoing)
        pending = await svc.confirm_outgoing(
            db_session, session_id=session.id, pin=PIN, end_type="SCHEDULED"
        )
        assert pending.status == "PENDING_HANDOVER"

        new_session = await svc.confirm_incoming(
            db_session,
            pending_session_id=pending.id,
            worker_id=incoming.id,
            pin=PIN,
        )

        await db_session.refresh(pending)
        assert pending.status == "COMPLETED"
        assert pending.ended_at is not None
        assert new_session.status == "ACTIVE"
        assert new_session.worker_id == incoming.id
        assert new_session.previous_session_id == pending.id

    async def test_check_in_blocked_while_handover_pending(
        self, db_session: AsyncSession
    ):
        outgoing = await _worker(db_session)
        incoming = await _worker(db_session)
        gate = await _gate(db_session)

        session = await _check_in(db_session, gate, outgoing)
        await svc.confirm_outgoing(
            db_session, session_id=session.id, pin=PIN, end_type="EARLY"
        )

        with pytest.raises(HTTPException) as exc:
            await svc.check_in(
                db_session, gate_id=gate.id, worker_id=incoming.id, pin=PIN
            )
        assert exc.value.status_code == 409
        assert "confirm-incoming" in exc.value.detail

    async def test_outgoing_wrong_pin_rejected(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        gate = await _gate(db_session)
        session = await _check_in(db_session, gate, worker)

        with pytest.raises(HTTPException) as exc:
            await svc.confirm_outgoing(
                db_session, session_id=session.id, pin="9999"
            )
        assert exc.value.status_code == 401

    async def test_takeover_requires_pending_state(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        incoming = await _worker(db_session)
        gate = await _gate(db_session)
        session = await _check_in(db_session, gate, worker)

        with pytest.raises(HTTPException) as exc:
            await svc.confirm_incoming(
                db_session,
                pending_session_id=session.id,
                worker_id=incoming.id,
                pin=PIN,
            )
        assert exc.value.status_code == 409


class TestForceLeave:
    async def test_force_leave_completes_and_alerts(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        gate = await _gate(db_session)
        session = await _check_in(db_session, gate, worker)

        completed = await svc.force_leave(
            db_session, session_id=session.id, pin=PIN, reason="incoming no-show"
        )

        assert completed.status == "COMPLETED"
        assert completed.end_type == "FORCE_LEAVE"
        assert completed.end_reason == "incoming no-show"

        alert = (
            await db_session.execute(
                select(OperatorAlert).where(
                    OperatorAlert.alert_type == "WORKER_UNCOVERED"
                )
            )
        ).scalar_one()
        assert alert.gate_id == gate.id
        assert "uncovered" in alert.message.lower()

    async def test_force_leave_wrong_pin_rejected(self, db_session: AsyncSession):
        worker = await _worker(db_session)
        gate = await _gate(db_session)
        session = await _check_in(db_session, gate, worker)

        with pytest.raises(HTTPException) as exc:
            await svc.force_leave(
                db_session, session_id=session.id, pin="9999", reason="x"
            )
        assert exc.value.status_code == 401

    async def test_completed_session_cannot_be_force_left(
        self, db_session: AsyncSession
    ):
        worker = await _worker(db_session)
        gate = await _gate(db_session)
        session = await _check_in(db_session, gate, worker)
        await svc.confirm_outgoing(
            db_session, session_id=session.id, pin=PIN, end_type="SCHEDULED"
        )
        await svc.confirm_incoming(
            db_session,
            pending_session_id=session.id,
            worker_id=(await _worker(db_session)).id,
            pin=PIN,
        )

        with pytest.raises(HTTPException) as exc:
            await svc.force_leave(
                db_session, session_id=session.id, pin=PIN, reason="x"
            )
        assert exc.value.status_code == 409
