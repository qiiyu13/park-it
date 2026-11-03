"""Unified gate management routes."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.api_key import require_api_key
from api.app.middleware.auth import require_admin, require_auth, require_operator
from api.app.models.gate import Gate
from api.app.models.manual_open_log import ManualOpenLog
from api.app.models.user import User
from api.app.schemas.common import SuccessResponse
from api.app.schemas.gate import GateCreate, GateLaneConfigUpdate, GateResponse, GateUpdate
from api.app.schemas.gate_control import GateControlRequest, GateControlResponse
from api.app.services.audit import log_action
from api.app.services.gate_command import publish_command
from api.database import get_db
from shared.events import CloseGateCommand, OpenGateCommand
from shared.logging import get_logger

logger = get_logger("gate_routes")
router = APIRouter(prefix="/gates", tags=["Gates"])


@router.get("", response_model=list[GateResponse])
async def list_gates(
    direction: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> list[GateResponse]:
    """List all gates, optionally filtered by direction."""
    query = select(Gate)
    if direction:
        query = query.where(Gate.direction == direction.upper())
    result = await db.execute(query)
    gates = result.scalars().all()
    return [GateResponse.model_validate(g) for g in gates]


@router.post("", response_model=GateResponse, status_code=status.HTTP_201_CREATED)
async def create_gate(
    data: GateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> GateResponse:
    """Create a new gate (entry or exit)."""
    gate = Gate(**data.model_dump())
    db.add(gate)
    await db.commit()
    await db.refresh(gate)
    logger.info("gate_created", gate_id=gate.id, code=gate.code, direction=gate.direction)
    return GateResponse.model_validate(gate)


@router.get("/by-code/{code}", response_model=GateResponse)
async def get_gate_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> GateResponse:
    """Booth-authenticated gate lookup by code (machine-to-machine)."""
    result = await db.execute(select(Gate).where(Gate.code == code))
    gate = result.scalar_one_or_none()
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    return GateResponse.model_validate(gate)


@router.get("/{gate_id}", response_model=GateResponse)
async def get_gate(
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> GateResponse:
    """Get gate by ID."""
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    return GateResponse.model_validate(gate)


@router.patch("/{gate_id}", response_model=GateResponse)
async def update_gate(
    gate_id: int,
    data: GateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> GateResponse:
    """Update gate configuration."""
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(gate, field, value)

    await db.commit()
    await db.refresh(gate)
    logger.info("gate_updated", gate_id=gate.id)
    return GateResponse.model_validate(gate)


@router.patch("/{gate_id}/lane-config", response_model=GateResponse)
async def update_gate_lane_config(
    gate_id: int,
    data: GateLaneConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> GateResponse:
    """Update only the lane type and default vehicle type without touching other hardware config."""
    from sqlalchemy.orm.attributes import flag_modified

    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    hw = dict(gate.hardware_config)
    hw["lane_type"] = data.lane_type
    hw["default_vehicle_type_id"] = data.default_vehicle_type_id
    gate.hardware_config = hw
    flag_modified(gate, "hardware_config")

    await db.commit()
    await db.refresh(gate)
    logger.info("gate_lane_config_updated", gate_id=gate.id, lane_type=data.lane_type)
    return GateResponse.model_validate(gate)


@router.delete("/{gate_id}", response_model=SuccessResponse)
async def delete_gate(
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SuccessResponse:
    """Delete gate."""
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    await db.delete(gate)
    await db.commit()
    logger.info("gate_deleted", gate_id=gate_id)
    return SuccessResponse(message="Gate deleted")


@router.post("/{gate_id}/open", response_model=GateControlResponse)
async def open_gate(
    gate_id: int,
    req: GateControlRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> GateControlResponse:
    """Manually open a gate. Operator triggered; every open is audited."""
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    if not gate.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gate is not active")

    cmd = OpenGateCommand(gate_id=gate.code, reason=req.reason)
    msg_id = await publish_command(cmd)

    try:
        user_id = int(current_user["sub"])
    except (KeyError, TypeError, ValueError):
        user_id = None
    # opened_by is an FK to users; a token can outlive a deleted account.
    if user_id is not None and await db.get(User, user_id) is not None:
        db.add(
            ManualOpenLog(
                gate_id=gate.id,
                gate_type=gate.direction.lower(),
                opened_by=user_id,
                reason=req.reason[:100],
            )
        )
    if user_id is not None:
        await log_action(
            db,
            action="GATE_OPEN",
            user_id=user_id,
            username=current_user.get("username"),
            entity_type="Gate",
            entity_id=str(gate.id),
            details={"gate_code": gate.code, "reason": req.reason},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()

    logger.info("gate_open_commanded", gate_id=gate.code, reason=req.reason)
    return GateControlResponse(success=True, message="Gate open command sent", gate_id=gate.code, command_id=msg_id)


@router.post("/{gate_id}/close", response_model=GateControlResponse)
async def close_gate(
    gate_id: int,
    req: GateControlRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> GateControlResponse:
    """Manually close a gate (DUAL relay mode only)."""
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    if not gate.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gate is not active")
    if gate.relay_mode != "DUAL":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gate does not support close command (relay_mode must be DUAL)")

    cmd = CloseGateCommand(gate_id=gate.code, reason=req.reason)
    msg_id = await publish_command(cmd)
    try:
        user_id = int(current_user["sub"])
    except (KeyError, TypeError, ValueError):
        user_id = None
    if user_id is not None:
        await log_action(
            db,
            action="GATE_CLOSE",
            user_id=user_id,
            username=current_user.get("username"),
            entity_type="Gate",
            entity_id=str(gate.id),
            details={"gate_code": gate.code, "reason": req.reason},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
    logger.info("gate_close_commanded", gate_id=gate.code, reason=req.reason)
    return GateControlResponse(success=True, message="Gate close command sent", gate_id=gate.code, command_id=msg_id)


@router.get("/status/heartbeat")
async def gates_heartbeat_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> dict:
    """Return liveness map for all active gates.

    Two liveness sources, branched by direction:

    - **IN gates** run an autonomous `gate_in` daemon that writes short-TTL
      `gate:heartbeat:{code}` keys to Redis (state machine + controller health).
      Missing key (TTL >60s) → `online: false`.
    - **OUT gates** have no daemon — they are driven by booth_bridge, whose
      liveness lands in `Pos.last_seen_at` (POSTed to /api/pos/heartbeat every
      15s). We resolve the booth via `Gate.pos` and treat last_seen within 60s
      as online. OUT gates have no state machine / Compass controller, so
      `state` and `controller_ok` are left null (frontend renders online/offline
      only for these).
    """
    import json as _json
    from datetime import datetime

    from sqlalchemy import select

    from shared.redis import redis_client

    out_stale_seconds = 60

    await redis_client.connect()
    result = await db.execute(select(Gate).where(Gate.is_active == True))  # noqa: E712
    gates = list(result.scalars().all())

    now = datetime.now(UTC)
    out: list[dict] = []

    # Batch fetch all IN gate heartbeats in one pipeline
    in_gates = [g for g in gates if g.direction == "IN"]
    in_heartbeat_keys = [f"gate:heartbeat:{g.code}" for g in in_gates]
    in_heartbeat_values = await redis_client.client.mget(in_heartbeat_keys) if in_heartbeat_keys else []
    in_heartbeat_map = dict(zip(in_heartbeat_keys, in_heartbeat_values, strict=False))

    for g in gates:
        if g.direction == "OUT":
            pos = g.pos
            last_seen = pos.last_seen_at if pos else None
            online = bool(
                last_seen
                and (now - last_seen).total_seconds() <= out_stale_seconds
            )
            out.append({
                "code": g.code,
                "direction": g.direction,
                "online": online,
                "state": None,
                "controller_ok": None,
                "last_seen": last_seen.isoformat() if last_seen else None,
            })
            continue

        raw = in_heartbeat_map.get(f"gate:heartbeat:{g.code}")
        if raw:
            try:
                payload = _json.loads(raw)
            except ValueError:
                payload = {}
            out.append({
                "code": g.code,
                "direction": g.direction,
                "online": True,
                "state": payload.get("state"),
                "controller_ok": payload.get("controller_ok"),
                "last_seen": payload.get("ts"),
            })
        else:
            out.append({
                "code": g.code,
                "direction": g.direction,
                "online": False,
                "state": None,
                "controller_ok": None,
                "last_seen": None,
            })
    return {"gates": out}
