"""POS (booth) management routes."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.api_key import require_api_key
from api.app.middleware.auth import require_admin, require_auth
from api.app.models.gate import Gate
from api.app.models.parking_transaction import ParkingTransaction
from api.app.models.pos import Pos
from api.app.schemas.common import SuccessResponse
from api.app.schemas.pos import (
    BoothHeartbeat,
    BoothHeartbeatResponse,
    BoothRegisterRequest,
    PosCreate,
    PosResponse,
    PosUpdate,
)
from api.app.services.shift_utils import get_current_shift
from api.database import get_db
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("pos_routes")
router = APIRouter(prefix="/pos", tags=["POS / Booth"])


@router.get("/by-ip", response_model=PosResponse)
async def get_pos_by_ip(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> PosResponse:
    """Get POS booth by client IP address.

    Used by POS frontend to auto-detect which booth this PC belongs to.
    Falls back to X-Forwarded-For if behind a proxy.
    """
    # Get client IP (handle proxy)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else None

    if not client_ip:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not determine client IP")

    # Try exact match first
    result = await db.execute(select(Pos).where(Pos.ip_address == client_ip))
    pos = result.scalar_one_or_none()

    # Fallback: try matching without port or handle localhost
    if pos is None and client_ip in ("127.0.0.1", "::1", "localhost"):
        # For local development, return the first active POS
        result = await db.execute(select(Pos).where(Pos.is_active.is_(True)).limit(1))
        pos = result.scalar_one_or_none()

    if pos is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No POS booth configured for IP {client_ip}",
        )

    logger.info("pos_detected_by_ip", pos_id=pos.id, code=pos.code, ip=client_ip)
    return PosResponse.model_validate(pos)


@router.get("/shift-summary")
async def get_shift_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> dict:
    """Return current shift name, time range, and aggregated POS totals for today.

    Used by POS frontend status bar. Falls back to empty payload if no active shift.
    """
    # Shift totals are an operational-day concept: build tz-aware bounds in
    # the facility timezone. Comparing a naive local midnight to a timestamptz
    # column shifted the window by the UTC offset (7h in Jakarta).
    tz = ZoneInfo(get_settings().app_timezone)
    now = datetime.now(tz)
    today_start = datetime.combine(now.date(), time.min, tzinfo=tz)
    tomorrow_start = today_start + timedelta(days=1)

    # Resolve current shift by wall-clock time (handles overnight wrap)
    active_shift = await get_current_shift(db)

    # Aggregate today's completed cash transactions for current operator
    operator_id = current_user.get("sub")
    try:
        operator_id_int = int(operator_id) if operator_id is not None else None
    except (TypeError, ValueError):
        operator_id_int = None

    cash_q = select(
        func.coalesce(func.sum(ParkingTransaction.paid_amount), 0),
        func.count(ParkingTransaction.id),
    ).where(
        ParkingTransaction.exit_time >= today_start,
        ParkingTransaction.exit_time < tomorrow_start,
        ParkingTransaction.payment_method == "CASH",
    )
    if operator_id_int is not None:
        cash_q = cash_q.where(ParkingTransaction.operator_id == operator_id_int)

    cash_collected, transaction_count = (await db.execute(cash_q)).one()

    if active_shift:
        time_range = f"{active_shift.start_time.strftime('%H:%M')} - {active_shift.end_time.strftime('%H:%M')}"
        shift_name = active_shift.name
    else:
        shift_name = ""
        time_range = ""

    return {
        "shift_name": shift_name,
        "shift_time_range": time_range,
        "cash_collected": int(cash_collected or 0),
        "transaction_count": int(transaction_count or 0),
    }


@router.post("/heartbeat", response_model=BoothHeartbeatResponse)
async def booth_heartbeat(
    payload: BoothHeartbeat,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_api_key),
) -> BoothHeartbeatResponse:
    """Booth liveness check.

    Authenticated by ``X-API-Key`` (the same INTERNAL_API_KEY the booth
    received via the enrollment flow). booth_bridge POSTs every 15s; we
    record ``last_seen_at`` and the self-reported status snapshot so admin
    UI + parking-doctor can show which booths are alive without an operator
    phone call.

    A heartbeat for an unknown booth_code is rejected with 404 rather than
    silently auto-creating a Pos row — the wizard owns booth registration.
    """
    result = await db.execute(select(Pos).where(Pos.code == payload.booth_code))
    pos = result.scalar_one_or_none()
    if pos is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown booth_code {payload.booth_code} — register it in the wizard first.",
        )

    now = datetime.now(UTC)
    pos.last_seen_at = now
    pos.last_status = {
        "rfid_connected": payload.rfid_connected,
        "gate_connected": payload.gate_connected,
        "ws_clients": payload.ws_clients,
        "last_card_at": payload.last_card_at,
        "bridge_version": payload.bridge_version,
    }
    await db.commit()
    return BoothHeartbeatResponse(booth_code=pos.code, last_seen_at=now)


@router.post("/register", response_model=PosResponse, status_code=status.HTTP_201_CREATED)
async def register_booth(
    payload: BoothRegisterRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(require_api_key),
) -> PosResponse:
    """Enrolled booth self-registration (machine-to-machine).

    Replaces the manual "add POS row" step in the admin UI. A booth that
    completed enrollment already holds the server-wide API key, so creating
    its own row is no additional privilege. Idempotent by booth_code.
    """
    gate = None
    if payload.default_gate_code:
        gate = (
            await db.execute(
                select(Gate).where(Gate.code == payload.default_gate_code)
            )
        ).scalar_one_or_none()

    result = await db.execute(select(Pos).where(Pos.code == payload.booth_code))
    pos = result.scalar_one_or_none()
    if pos is None:
        pos = Pos(
            name=payload.name,
            code=payload.booth_code,
            ip_address=payload.ip_address,
            default_gate_id=gate.id if gate else None,
            booth_peripherals={},
            is_active=True,
        )
        db.add(pos)
    else:
        pos.name = payload.name
        if payload.ip_address:
            pos.ip_address = payload.ip_address
        if gate is not None:
            pos.default_gate_id = gate.id
        pos.is_active = True

    await db.commit()
    await db.refresh(pos)
    logger.info(
        "booth_registered",
        pos_id=pos.id,
        code=pos.code,
        gate=payload.default_gate_code,
        gate_found=gate is not None,
    )
    return PosResponse.model_validate(pos)


@router.get("", response_model=list[PosResponse])
async def list_pos(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> list[PosResponse]:
    """List all POS booths."""
    result = await db.execute(select(Pos))
    pos_list = result.scalars().all()
    return [PosResponse.model_validate(p) for p in pos_list]


@router.post("", response_model=PosResponse, status_code=status.HTTP_201_CREATED)
async def create_pos(
    data: PosCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> PosResponse:
    """Create a new POS booth."""
    pos = Pos(**data.model_dump())
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    logger.info("pos_created", pos_id=pos.id, code=pos.code)
    return PosResponse.model_validate(pos)


@router.get("/{pos_id}", response_model=PosResponse)
async def get_pos(
    pos_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> PosResponse:
    """Get POS by ID."""
    pos = await db.get(Pos, pos_id)
    if pos is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS not found")
    return PosResponse.model_validate(pos)


@router.patch("/{pos_id}", response_model=PosResponse)
async def update_pos(
    pos_id: int,
    data: PosUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> PosResponse:
    """Update POS configuration."""
    pos = await db.get(Pos, pos_id)
    if pos is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(pos, field, value)

    await db.commit()
    await db.refresh(pos)
    logger.info("pos_updated", pos_id=pos.id)
    return PosResponse.model_validate(pos)


@router.delete("/{pos_id}", response_model=SuccessResponse)
async def delete_pos(
    pos_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SuccessResponse:
    """Delete POS booth."""
    pos = await db.get(Pos, pos_id)
    if pos is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POS not found")
    await db.delete(pos)
    await db.commit()
    logger.info("pos_deleted", pos_id=pos_id)
    return SuccessResponse(message="POS deleted")
