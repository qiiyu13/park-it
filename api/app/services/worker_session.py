"""Worker session service — handover state machine and check-in logic."""

from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.gate import Gate
from api.app.models.operator_alert import OperatorAlert
from api.app.models.shift_assignment import ShiftAssignment
from api.app.models.user import User
from api.app.models.worker_session import WorkerSession
from api.app.services.shift_utils import get_current_shift
from api.app.utils.password import verify_password
from shared.logging import get_logger

logger = get_logger("worker_session_service")


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


async def _get_worker_and_verify_pin(db: AsyncSession, worker_id: int, pin: str) -> User:
    """Fetch worker and verify PIN. Raises 401 on mismatch, 404 if not found."""
    worker = await db.get(User, worker_id)
    if worker is None or not worker.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    if not worker.worker_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Worker has no PIN set — contact admin",
        )
    if not verify_password(pin, worker.worker_pin):
        logger.warning("worker_pin_mismatch", worker_id=worker_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid PIN")
    return worker


async def _get_active_session(db: AsyncSession, gate_id: int) -> WorkerSession | None:
    """Get ACTIVE or PENDING_HANDOVER session for a gate."""
    result = await db.execute(
        select(WorkerSession).where(
            and_(
                WorkerSession.gate_id == gate_id,
                WorkerSession.status.in_(["ACTIVE", "PENDING_HANDOVER"]),
            )
        )
    )
    return result.scalar_one_or_none()


async def get_active_session(db: AsyncSession, gate_id: int) -> WorkerSession | None:
    """Public: get current active/pending session for a gate."""
    return await _get_active_session(db, gate_id)


async def check_in(
    db: AsyncSession,
    gate_id: int,
    worker_id: int,
    pin: str,
    shift_assignment_id: int | None = None,
    is_substitute: bool = False,
    original_worker_id: int | None = None,
) -> WorkerSession:
    """Worker checks in at a gate. Creates new WorkerSession with status=ACTIVE.

    Validates: no conflicting active session, PIN correct, gate exists, shift found.
    """
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    # Verifies the PIN as a side effect (raises on mismatch); the worker row
    # itself isn't needed here since worker_id is already known.
    await _get_worker_and_verify_pin(db, worker_id, pin)

    existing = await _get_active_session(db, gate_id)
    if existing is not None and existing.status == "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gate already has an active worker session",
        )
    if existing is not None and existing.status == "PENDING_HANDOVER":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use confirm-incoming endpoint to complete pending handover",
        )

    # Determine shift
    shift_id: int | None = None
    if shift_assignment_id is not None:
        assignment = await db.get(ShiftAssignment, shift_assignment_id)
        if assignment is None or assignment.gate_id != gate_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid shift assignment"
            )
        shift_id = assignment.shift_id
    else:
        active_shift = await get_current_shift(db)
        if active_shift is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No active shift for current time"
            )
        shift_id = active_shift.id

    now = _now()
    session = WorkerSession(
        shift_id=shift_id,
        shift_assignment_id=shift_assignment_id,
        worker_id=worker_id,
        gate_id=gate_id,
        date=_today(),
        status="ACTIVE",
        started_at=now,
        is_substitute=is_substitute,
    )
    if is_substitute and original_worker_id is not None:
        # WorkerSession has no original_worker_id column (provenance lives on
        # the planned ShiftAssignment); log it so the substitution is auditable.
        logger.info(
            "substitute_checked_in",
            session_id=None,
            worker_id=worker_id,
            original_worker_id=original_worker_id,
            gate_id=gate_id,
        )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info("worker_checked_in", session_id=session.id, worker_id=worker_id, gate_id=gate_id)
    return session


async def confirm_outgoing(
    db: AsyncSession,
    session_id: int,
    pin: str,
    end_type: str = "SCHEDULED",
    end_reason: str | None = None,
) -> WorkerSession:
    """Outgoing worker confirms they are leaving — transitions session to PENDING_HANDOVER."""
    session = await db.get(WorkerSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {session.status}, must be ACTIVE",
        )

    await _get_worker_and_verify_pin(db, session.worker_id, pin)

    now = _now()
    session.outgoing_confirmed_at = now
    session.status = "PENDING_HANDOVER"
    session.end_type = end_type
    session.end_reason = end_reason

    await db.commit()
    await db.refresh(session)
    logger.info(
        "outgoing_confirmed",
        session_id=session_id,
        worker_id=session.worker_id,
        end_type=end_type,
    )
    return session


async def confirm_incoming(
    db: AsyncSession,
    pending_session_id: int,
    worker_id: int,
    pin: str,
    is_substitute: bool = False,
    original_worker_id: int | None = None,
) -> WorkerSession:
    """Incoming worker confirms takeover — completes handover and starts new session."""
    pending = await db.get(WorkerSession, pending_session_id)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if pending.status != "PENDING_HANDOVER":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {pending.status}, must be PENDING_HANDOVER",
        )

    await _get_worker_and_verify_pin(db, worker_id, pin)

    now = _now()

    # Close outgoing session
    pending.ended_at = now
    pending.status = "COMPLETED"

    # Determine new shift
    active_shift = await get_current_shift(db)
    shift_id = active_shift.id if active_shift else pending.shift_id

    # Create incoming session
    new_session = WorkerSession(
        shift_id=shift_id,
        shift_assignment_id=None,
        worker_id=worker_id,
        gate_id=pending.gate_id,
        date=_today(),
        status="ACTIVE",
        started_at=now,
        is_substitute=is_substitute,
        previous_session_id=pending.id,
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    logger.info(
        "incoming_confirmed",
        new_session_id=new_session.id,
        prev_session_id=pending_session_id,
        worker_id=worker_id,
    )
    return new_session


async def force_leave(
    db: AsyncSession,
    session_id: int,
    pin: str,
    reason: str,
) -> WorkerSession:
    """Outgoing force-leaves after no-show incoming. Ends session, fires admin alert."""
    session = await db.get(WorkerSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status not in ("ACTIVE", "PENDING_HANDOVER"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {session.status}, cannot force-leave",
        )

    await _get_worker_and_verify_pin(db, session.worker_id, pin)

    gate = await db.get(Gate, session.gate_id)
    gate_direction = gate.direction.lower() if gate else "out"

    now = _now()
    session.ended_at = now
    session.status = "COMPLETED"
    session.end_type = "FORCE_LEAVE"
    session.end_reason = reason

    alert = OperatorAlert(
        gate_type=gate_direction,
        gate_id=session.gate_id,
        alert_type="WORKER_UNCOVERED",
        message=(
            f"Worker (id={session.worker_id}) force-left gate {session.gate_id}. "
            f"Booth is now uncovered. Reason: {reason}"
        ),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(session)
    logger.warning(
        "worker_force_left",
        session_id=session_id,
        worker_id=session.worker_id,
        gate_id=session.gate_id,
    )
    return session
