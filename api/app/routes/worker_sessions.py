"""Worker session routes — check-in, handover, force-leave."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin, require_operator
from api.app.models.worker_session import WorkerSession
from api.app.schemas.worker_session import (
    CheckInRequest,
    ConfirmIncomingRequest,
    ConfirmOutgoingRequest,
    ForceLeaveRequest,
    WorkerSessionResponse,
)
from api.app.services import worker_session as svc
from api.database import get_db
from shared.logging import get_logger

logger = get_logger("worker_session_routes")

router = APIRouter(prefix="/worker-sessions", tags=["Worker Sessions"])


@router.get("/active", response_model=WorkerSessionResponse | None)
async def get_active_session(
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> WorkerSessionResponse | None:
    """Get current active or pending-handover session for a gate."""
    session = await svc.get_active_session(db, gate_id)
    if session is None:
        return None
    return WorkerSessionResponse.model_validate(session)


@router.get("", response_model=list[WorkerSessionResponse])
async def list_worker_sessions(
    gate_id: int | None = None,
    worker_id: int | None = None,
    date_filter: date | None = None,
    session_status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> list[WorkerSessionResponse]:
    """List worker sessions with optional filters (admin only)."""
    stmt = select(WorkerSession).order_by(WorkerSession.started_at.desc())
    if gate_id is not None:
        stmt = stmt.where(WorkerSession.gate_id == gate_id)
    if worker_id is not None:
        stmt = stmt.where(WorkerSession.worker_id == worker_id)
    if date_filter is not None:
        stmt = stmt.where(WorkerSession.date == date_filter)
    if session_status is not None:
        stmt = stmt.where(WorkerSession.status == session_status)
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return [WorkerSessionResponse.model_validate(s) for s in sessions]


@router.get("/{session_id}/summary")
async def get_session_summary(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> dict:
    """Takings for this session (Tunai / E-Money / Member), shown before handover."""
    session = await db.get(WorkerSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return await svc.session_summary(db, session)


@router.post("/check-in", response_model=WorkerSessionResponse, status_code=status.HTTP_201_CREATED)
async def check_in(
    data: CheckInRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> WorkerSessionResponse:
    """Worker checks in at a gate. Creates new active session."""
    session = await svc.check_in(
        db,
        gate_id=data.gate_id,
        worker_id=data.worker_id,
        shift_assignment_id=data.shift_assignment_id,
        is_substitute=data.is_substitute,
        original_worker_id=data.original_worker_id,
    )
    return WorkerSessionResponse.model_validate(session)


@router.post("/{session_id}/confirm-outgoing", response_model=WorkerSessionResponse)
async def confirm_outgoing(
    session_id: int,
    data: ConfirmOutgoingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> WorkerSessionResponse:
    """Outgoing worker confirms departure — transitions session to PENDING_HANDOVER."""
    session = await svc.confirm_outgoing(
        db,
        session_id=session_id,
        end_type=data.end_type,
        end_reason=data.end_reason,
    )
    await svc.enqueue_shift_slip(db, session)
    return WorkerSessionResponse.model_validate(session)


@router.post("/{session_id}/confirm-incoming", response_model=WorkerSessionResponse, status_code=status.HTTP_201_CREATED)
async def confirm_incoming(
    session_id: int,
    data: ConfirmIncomingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> WorkerSessionResponse:
    """Incoming worker confirms takeover — completes handover and starts new session."""
    session = await svc.confirm_incoming(
        db,
        pending_session_id=session_id,
        worker_id=data.worker_id,
        is_substitute=data.is_substitute,
        original_worker_id=data.original_worker_id,
    )
    return WorkerSessionResponse.model_validate(session)


@router.post("/{session_id}/force-leave", response_model=WorkerSessionResponse)
async def force_leave(
    session_id: int,
    data: ForceLeaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> WorkerSessionResponse:
    """Outgoing force-leaves after no-show incoming. Fires admin alert, booth goes uncovered."""
    existing = await db.get(WorkerSession, session_id)
    slip_printed = existing is not None and existing.status == "PENDING_HANDOVER"
    session = await svc.force_leave(
        db,
        session_id=session_id,
        reason=data.reason,
    )
    if not slip_printed:  # leaving straight from ACTIVE: no slip was printed yet
        await svc.enqueue_shift_slip(db, session)
    return WorkerSessionResponse.model_validate(session)
