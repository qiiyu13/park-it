"""Unified gate management routes."""

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.api_key import require_api_key
from api.app.middleware.auth import require_admin, require_auth, require_operator
from api.app.models.gate import Gate
from api.app.models.manual_open_log import ManualOpenLog
from api.app.models.pos import Pos
from api.app.models.user import User
from api.app.schemas.common import SuccessResponse
from api.app.schemas.gate import GateCreate, GateLaneConfigUpdate, GateResponse, GateUpdate
from api.app.schemas.gate_control import GateControlRequest, GateControlResponse, ManualOpenRequest
from api.app.services.audit import log_action
from api.app.services.gate_command import publish_command
from api.app.services.snapshot_utils import resolve_gate_cameras
from api.app.utils.password import verify_password
from api.database import get_db
from shared.events import CloseGateCommand, OpenGateCommand
from shared.logging import get_logger
from shared.redis import redis_client

logger = get_logger("gate_routes")
router = APIRouter(prefix="/gates", tags=["Gates"])


async def _publish_gate_config_changed(gate_code: str) -> None:
    """Tell the running daemon to reload without a systemctl restart."""
    try:
        await redis_client.connect()
        await redis_client.client.publish(
            f"parking.config.gate.{gate_code}",
            json.dumps({"gate_id": gate_code, "event": "config_changed"}),
        )
        logger.info("gate_config_change_published", gate_id=gate_code)
    except Exception as exc:  # daemon polling is the fallback
        logger.warning("gate_config_change_publish_failed", gate_id=gate_code, error=str(exc))


async def _gate_responses(gates: list[Gate], db: AsyncSession) -> list[GateResponse]:
    """Serialize gates with live online status.

    The daemon only publishes `gate:heartbeat:{code}` to Redis (60s TTL); the
    `is_online` / `last_heartbeat` columns in the gates table are never
    written, so reading them made every healthy lane look offline in the UI.
    """
    try:
        await redis_client.connect()
        for gate in gates:
            raw = await redis_client.client.get(f"gate:heartbeat:{gate.code}")
            if raw:
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {}
                gate.is_online = True
                gate.last_heartbeat = payload.get("ts")
                # Hardware link (controller); heartbeat itself only proves the
                # daemon is alive.
                gate.controller_ok = bool(payload.get("controller_ok", True))
            else:
                gate.is_online = False
                gate.controller_ok = False
                gate.last_heartbeat = None
                # Exit lanes have no daemon — their relay is driven by the booth
                # bridge on the cashier PC. Treat a fresh booth heartbeat (with
                # the relay actually open/connected) as this lane being online.
                if gate.direction == "OUT" and gate.pos_id:
                    pos = await db.get(Pos, gate.pos_id)
                    seen = pos.last_seen_at if pos else None
                    status = (pos.last_status or {}) if pos else {}
                    if seen is not None and seen.tzinfo is None:
                        seen = seen.replace(tzinfo=UTC)
                    fresh = seen is not None and (datetime.now(UTC) - seen) < timedelta(seconds=90)
                    if fresh:
                        # Bridge alive; the relay itself is reported separately
                        # via controller_ok (Gate Barrier row).
                        gate.is_online = True
                        gate.controller_ok = bool(status.get("gate_connected"))
                        gate.last_heartbeat = seen.isoformat()
    except Exception as exc:  # Redis down: fall back to stored values
        logger.warning("gate_live_status_unavailable", error=str(exc))

    # Expand shared camera references for the UI. Done on the response copy, not
    # on the ORM object — get_db() commits at the end of the request and a
    # mutated hardware_config would be written back to the database.
    responses: list[GateResponse] = []
    for gate in gates:
        data = GateResponse.model_validate(gate).model_dump()
        try:
            cameras = await resolve_gate_cameras(db, gate)
        except Exception as exc:
            logger.warning("gate_camera_expand_failed", gate_id=gate.code, error=str(exc))
            cameras = []
        if cameras:
            data["hardware_config"] = {
                **(data.get("hardware_config") or {}),
                "cameras": cameras,
            }
        responses.append(GateResponse.model_validate(data))
    return responses


async def _gate_response(gate: Gate, db: AsyncSession) -> GateResponse:
    return (await _gate_responses([gate], db))[0]


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
    # Stable card order in the UI: IN lanes first, then OUT, each by code
    # (GIN-01, GIN-02, GIN-03, GOUT-01, GOUT-02). Without ORDER BY Postgres is
    # free to return rows in any order, which made the cards swap places.
    query = query.order_by(Gate.direction.asc(), Gate.code.asc())
    result = await db.execute(query)
    gates = list(result.scalars().all())
    return await _gate_responses(gates, db)


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
    return await _gate_response(gate, db)


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
    return await _gate_response(gate, db)


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
    return await _gate_response(gate, db)


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
    await _publish_gate_config_changed(gate.code)
    logger.info("gate_updated", gate_id=gate.id)
    return await _gate_response(gate, db)


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
    await _publish_gate_config_changed(gate.code)
    logger.info("gate_lane_config_updated", gate_id=gate.id, lane_type=data.lane_type)
    return await _gate_response(gate, db)


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
    gate_code = gate.code
    await db.delete(gate)
    await db.commit()
    await _publish_gate_config_changed(gate_code)
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

    # Booth-driven serial lanes are opened by booth_bridge on the cashier PC.
    # There is no daemon consuming the Redis stream for them, so queue the
    # command for the bridge's 2s poller instead of faking success.
    if gate.direction == "OUT" and gate.protocol == "serial":
        if gate.pos_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Gate ini belum punya perangkat relay terpasang — hardware belum ada.",
            )

        booth = await db.get(Pos, gate.pos_id)
        booth_status = (booth.last_status or {}) if booth else {}
        seen = booth.last_seen_at if booth else None
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=UTC)
        booth_fresh = seen is not None and (datetime.now(UTC) - seen) < timedelta(seconds=90)
        if not booth_fresh or not booth_status.get("gate_connected"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Booth kasir untuk gate ini tidak terhubung — periksa relay/PC kasir.",
            )

        await redis_client.connect()
        await redis_client.client.set(
            f"gate:pending_open:{gate.code}",
            json.dumps(
                {
                    "gate_code": gate.code,
                    "reason": req.reason,
                    "requested_by": current_user.get("username"),
                    "requested_at": datetime.now(UTC).isoformat(),
                }
            ),
            ex=15,
        )

        try:
            user_id = int(current_user["sub"])
        except (KeyError, TypeError, ValueError):
            user_id = None
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
                details={"gate_code": gate.code, "reason": req.reason, "via": "booth_queue"},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            await db.commit()

        logger.info("gate_open_queued_for_booth", gate_id=gate.code, reason=req.reason)
        return GateControlResponse(
            success=True,
            message="Perintah buka dikirim ke booth kasir",
            gate_id=gate.code,
        )

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


@router.post("/{gate_id}/manual-open", response_model=GateControlResponse)
async def manual_open_gate(
    gate_id: int,
    req: ManualOpenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> GateControlResponse:
    """Manual open authorised by a supervisor/admin password.

    Used by the POS for exceptional cases (lost ticket, sensor failure, or
    testing the barrier). The operator session alone is not enough: only
    supervisor/admin accounts may authorise the open, and every attempt is
    recorded in the audit trail + manual_open_logs.
    """
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    if not gate.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gate is not active")

    result = await db.execute(select(User).where(User.username == req.username))
    supervisor = result.scalar_one_or_none()
    if (
        supervisor is None
        or not supervisor.is_active
        or supervisor.role not in ("supervisor", "admin")
        or not verify_password(req.password, supervisor.password_hash)
    ):
        logger.warning("manual_open_denied", gate_id=gate.code, username=req.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password supervisor salah",
        )

    db.add(
        ManualOpenLog(
            gate_id=gate.id,
            gate_type=gate.direction.lower(),
            opened_by=supervisor.id,
            reason=req.reason[:100],
        )
    )
    await log_action(
        db,
        action="GATE_MANUAL_OPEN",
        user_id=supervisor.id,
        username=supervisor.username,
        entity_type="Gate",
        entity_id=str(gate.id),
        details={
            "gate_code": gate.code,
            "authorised_by": supervisor.username,
            "session_user": current_user.get("username"),
            "reason": req.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    # Booth-driven serial lanes are physically opened by booth_bridge over its
    # local websocket; the POS sends that command after this authorisation.
    command_id: str | None = None
    if not (gate.direction == "OUT" and gate.protocol == "serial" and gate.pos_id is not None):
        command_id = await publish_command(OpenGateCommand(gate_id=gate.code, reason=req.reason))

    logger.info(
        "gate_manual_open_authorised",
        gate_id=gate.code,
        supervisor=supervisor.username,
        reason=req.reason,
    )
    return GateControlResponse(
        success=True,
        message="Manual open authorised",
        gate_id=gate.code,
        command_id=command_id,
    )


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


@router.post("/{gate_id}/enable-daemon")
async def enable_gate_daemon(
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> dict:
    """Enable + start the gate-in daemon for this lane.

    A gate added through the UI has no systemd instance yet — the installer only
    enables daemons for gates that existed at install time. Technicians used to
    run `systemctl enable --now parking-daemon-gate-in@<CODE>` by hand.
    """
    gate = await db.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    if gate.direction != "IN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exit lanes are driven by booth_bridge — no gate daemon to enable",
        )
    if not gate.controller_host and not gate.controller_device:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gate has no controller configured — fill host/port or serial device first",
        )

    script = Path(__file__).resolve().parents[3] / "scripts" / "gate-daemon-control.sh"
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", str(script), gate.code, "enable",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except (TimeoutError, FileNotFoundError) as exc:
        raise HTTPException(status_code=503, detail=f"daemon control unavailable: {exc}")

    if proc.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", errors="ignore").strip()[:300]
        raise HTTPException(status_code=502, detail=f"failed to enable daemon: {detail}")

    state = stdout.decode("utf-8", errors="ignore").strip().splitlines()[-1:] or ["unknown"]
    logger.info("gate_daemon_enabled", gate_id=gate.code, state=state[0])
    return {"success": True, "gate": gate.code, "state": state[0]}


@router.get("/{code}/logs")
async def gate_daemon_logs(
    code: str,
    lines: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> dict:
    """Live technician log for a lane's gate daemon (journalctl tail).

    Read via the root wrapper scripts/gate-logs.sh (NOPASSWD sudoers entry):
    the daemon runs as a system unit, so its journal is not readable by the
    `parking` service user directly.
    """
    gate = (
        await db.execute(select(Gate).where(Gate.code == code))
    ).scalar_one_or_none()
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")

    script = Path(__file__).resolve().parents[3] / "scripts" / "gate-logs.sh"
    lines = max(10, min(lines, 1000))
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", str(script), code, str(lines),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except (TimeoutError, FileNotFoundError) as exc:
        raise HTTPException(status_code=503, detail=f"log reader unavailable: {exc}")

    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="ignore").strip()[:200]
        raise HTTPException(status_code=503, detail=f"log reader failed: {detail}")

    entries: list[dict] = []
    for raw in stdout.decode("utf-8", errors="ignore").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            entries.append({"ts": None, "level": "info", "event": "raw", "message": raw})
            continue
        # MESSAGE carries the daemon's own JSON log line.
        msg = item.get("MESSAGE", "")
        if isinstance(msg, bytes):
            msg = msg.decode("utf-8", errors="ignore")
        ts_us = item.get("__REALTIME_TIMESTAMP")
        ts = None
        if ts_us:
            with contextlib.suppress(TypeError, ValueError):
                ts = datetime.fromtimestamp(int(ts_us) / 1_000_000, tz=UTC).isoformat()
        try:
            parsed = json.loads(msg) if isinstance(msg, str) else None
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            entries.append({
                "ts": parsed.get("timestamp") or ts,
                "level": parsed.get("level", "info"),
                "event": parsed.get("event", "log"),
                "message": {k: v for k, v in parsed.items()
                            if k not in ("timestamp", "level", "event")},
            })
        else:
            entries.append({"ts": ts, "level": "info", "event": "log", "message": msg})
    return {"gate": code, "lines": len(entries), "entries": entries}


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
