"""Worker session service — handover state machine and check-in logic."""

from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.gate import Gate
from api.app.models.operator_alert import OperatorAlert
from api.app.models.parking_transaction import ParkingTransaction
from api.app.models.shift_assignment import ShiftAssignment
from api.app.models.user import User
from api.app.models.worker_session import WorkerSession
from api.app.services.shift_utils import get_current_shift
from shared.logging import get_logger

logger = get_logger("worker_session_service")


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


async def _get_worker(db: AsyncSession, worker_id: int) -> User:
    """Fetch an active worker. No PIN: the client picks workers by name only."""
    worker = await db.get(User, worker_id)
    if worker is None or not worker.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Petugas tidak ditemukan atau nonaktif — periksa menu Personil")
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
    shift_assignment_id: int | None = None,
    is_substitute: bool = False,
    original_worker_id: int | None = None,
) -> WorkerSession:
    """Worker checks in at a gate. Creates new WorkerSession with status=ACTIVE.

    Validates: no conflicting active session, worker active, gate exists, shift found.
    """
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    await _get_worker(db, worker_id)

    existing = await _get_active_session(db, gate_id)
    if existing is not None and existing.status == "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gate ini sudah ada petugas aktif — gunakan serah terima (handover) di badge petugas",
        )
    if existing is not None and existing.status == "PENDING_HANDOVER":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ada serah terima tertunda di gate ini — selesaikan konfirmasi petugas baru",
        )

    # Determine shift
    shift_id: int | None = None
    if shift_assignment_id is not None:
        assignment = await db.get(ShiftAssignment, shift_assignment_id)
        if assignment is None or assignment.gate_id != gate_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Penugasan tidak cocok dengan gate ini — pilih penugasan hari ini untuk gate yang sama (Jadwal Shift → Penugasan)"
            )
        shift_id = assignment.shift_id
    else:
        active_shift = await get_current_shift(db)
        if active_shift is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Belum ada shift aktif untuk jam sekarang — buat master Shift dulu di Jadwal Shift → tab Shift, atau buat penugasan hari ini"
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


async def session_summary(db: AsyncSession, session: WorkerSession) -> dict:
    """Takings at the session's exit gate between check-in and handover.

    Transactions carry the login user, not the worker who entered a PIN, so the
    session is matched by gate and time window instead. The window closes at
    the outgoing confirmation (or force-leave), else now for a live preview.
    Amounts use the fee, not paid_amount: paid_amount includes the change.
    """
    from zoneinfo import ZoneInfo

    from shared.config import get_settings

    closed_at = session.outgoing_confirmed_at or session.ended_at or _now()
    rows = await db.execute(
        select(
            ParkingTransaction.payment_method,
            func.count(ParkingTransaction.id),
            func.coalesce(func.sum(ParkingTransaction.fee), 0),
        )
        .where(
            ParkingTransaction.gate_out_id == session.gate_id,
            ParkingTransaction.status == "COMPLETED",
            ParkingTransaction.exit_time >= session.started_at,
            ParkingTransaction.exit_time < closed_at,
        )
        .group_by(ParkingTransaction.payment_method)
    )
    by_method = {
        (method or "LAINNYA"): {"count": int(count), "amount": int(amount)}
        for method, count, amount in rows.all()
    }
    tz = ZoneInfo(get_settings().app_timezone)
    gate = await db.get(Gate, session.gate_id)
    worker = await db.get(User, session.worker_id)
    return {
        "session_id": session.id,
        "worker_name": (worker.full_name or worker.username) if worker else "",
        "gate_code": gate.code if gate else "",
        "gate_name": gate.name if gate else "",
        "shift_name": session.shift.name if session.shift else "",
        "started_at": session.started_at.astimezone(tz).isoformat(),
        "closed_at": closed_at.astimezone(tz).isoformat(),
        "by_method": by_method,
        "cash_amount": by_method.get("CASH", {}).get("amount", 0),
        "total_amount": sum(m["amount"] for m in by_method.values()),
        "total_count": sum(m["count"] for m in by_method.values()),
    }


async def enqueue_shift_slip(db: AsyncSession, session: WorkerSession) -> None:
    """Print the closing slip on the gate's receipt printer (best effort)."""
    try:
        summary = await session_summary(db, session)
        gate = await db.get(Gate, session.gate_id)
        if gate is None or not gate.is_peripheral_enabled("receipt_printer"):
            logger.info("shift_slip_skipped_no_printer", session_id=session.id)
            return
        from shared.redis import get_arq_redis

        arq_redis = await get_arq_redis()
        await arq_redis.enqueue_job(
            "print_shift_slip",
            gate_id=gate.code,
            summary=summary,
            _job_id=f"shift-slip:{session.id}",
        )
        logger.info("shift_slip_enqueued", session_id=session.id, gate_id=gate.code)
    except Exception as exc:  # a printer problem must never block the handover
        logger.error("shift_slip_enqueue_failed", session_id=session.id, error=str(exc))


async def confirm_outgoing(
    db: AsyncSession,
    session_id: int,
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

    await _get_worker(db, session.worker_id)

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

    await _get_worker(db, worker_id)

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

    await _get_worker(db, session.worker_id)

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
