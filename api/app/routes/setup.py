"""Setup wizard routes — token redeem, admin create, preflight, state I/O.

Authentication model:
- `/api/setup/redeem-token` is the only un-auth endpoint. It validates a
  one-time token written to disk by the installer, sets a setup-session
  cookie (`parking_setup_session`), and returns a fresh setup session row.
- Subsequent endpoints accept either a valid setup session cookie OR an
  admin JWT. This allows re-running the wizard via `/setup?force=1` after
  initial setup.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import get_current_user
from api.app.models.gate import Gate
from api.app.models.setup_session import SetupSession
from api.app.models.user import User
from api.app.schemas.common import SuccessResponse
from api.app.schemas.setup import (
    CreateAdminRequest,
    DetectSerialCandidate,
    DetectSerialResponse,
    DiscoverGateCandidate,
    DiscoverGatesRequest,
    DiscoverGatesResponse,
    EnrollRequest,
    EnrollResponse,
    FinalizeResponse,
    PreflightCheckResult,
    PreflightResponse,
    RedeemTokenRequest,
    SetupStateResponse,
    SetupStateUpdate,
    TestDeviceRequest,
    TestDeviceResponse,
    TestGateRequest,
    TestGateResponse,
    TestGateStep,
    TopologyApplyRequest,
    WriteUdevRequest,
    WriteUdevResponse,
)
from api.app.schemas.user import UserResponse
from api.app.services.auth import create_tokens
from api.app.services.gate_command import publish_command
from api.app.services.setup import (
    constant_time_eq,
    create_session,
    delete_session,
    delete_setup_token,
    detect_topology,
    get_session_by_token,
    has_any_admin,
    mark_setup_complete,
    read_enroll_token,
    read_setup_token,
    run_script_json,
    save_session_step,
)
from api.app.services.setup import (
    setup_complete as setup_complete_q,
)
from api.app.utils.password import hash_password
from api.database import get_db
from shared.config import get_settings
from shared.events import CloseGateCommand, OpenGateCommand
from shared.logging import get_logger
from shared.redis import redis_client

logger = get_logger("setup_routes")

router = APIRouter(prefix="/setup", tags=["Setup Wizard"])

SETUP_COOKIE_NAME = "parking_setup_session"


def _set_setup_cookie(response: Response, token: str) -> None:
    is_secure = get_settings().app_env == "production"
    response.set_cookie(
        key=SETUP_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="strict",
        max_age=get_settings().setup_session_ttl_seconds,
        path="/",
    )


def _clear_setup_cookie(response: Response) -> None:
    response.delete_cookie(key=SETUP_COOKIE_NAME, path="/")


async def require_setup_or_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[SetupSession | None, dict[str, Any] | None]:
    """Allow the request if either a valid setup-session cookie OR admin JWT is present."""
    cookie = request.cookies.get(SETUP_COOKIE_NAME)
    session: SetupSession | None = None
    if cookie:
        session = await get_session_by_token(db, cookie)

    user_payload = await get_current_user(request)
    is_admin = user_payload is not None and user_payload.get("role") == "admin"

    if session is None and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Setup session or admin authentication required",
        )
    return session, user_payload


@router.get("/state", response_model=SetupStateResponse)
async def get_state(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SetupStateResponse:
    """Wizard bootstrapping endpoint. Public (no auth)."""
    complete = await setup_complete_q(db)
    has_admin = await has_any_admin(db)
    topology = await detect_topology()

    cookie = request.cookies.get(SETUP_COOKIE_NAME)
    session: SetupSession | None = None
    if cookie:
        session = await get_session_by_token(db, cookie)

    return SetupStateResponse(
        setup_complete=complete,
        current_step=session.current_step if session else None,
        topology=topology,
        has_admin=has_admin,
        has_session=session is not None,
    )


@router.post("/redeem-token", response_model=SuccessResponse)
async def redeem_token(
    body: RedeemTokenRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    """Validate installer-written token and issue setup session cookie."""
    disk_token = read_setup_token()
    if not disk_token:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Setup token not present — installer must regenerate one.",
        )
    if not constant_time_eq(disk_token, body.token):
        logger.warning("setup_token_mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid setup token",
        )

    delete_setup_token()
    session = await create_session(db)
    _set_setup_cookie(response, session.session_token)
    logger.info("setup_session_created", session_id=session.id)
    return SuccessResponse(
        message="Setup session active",
        data={"current_step": session.current_step},
    )


@router.post("/enroll", response_model=EnrollResponse)
async def enroll_booth(
    body: EnrollRequest,
    request: Request,
) -> EnrollResponse:
    """Hand a booth PC the secrets it needs to join this server.

    Un-authenticated but gated by the installer-minted enrollment token
    (/etc/parking/enroll-token). Unlike the setup token, this one is reusable
    within its 24h window so every booth brought online during the install can
    enroll with the same token. Replaces the old hand-copied INTERNAL_API_KEY.
    """
    disk_token = read_enroll_token()
    if not disk_token:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Enrollment token not present — regenerate with scripts/regen-enroll-token.sh.",
        )
    if not constant_time_eq(disk_token, body.token):
        client = request.client.host if request.client else "unknown"
        logger.warning("enroll_token_mismatch", source_ip=client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid enrollment token",
        )

    settings = get_settings()
    if not settings.internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server has no INTERNAL_API_KEY configured — cannot enroll booths.",
        )

    client = request.client.host if request.client else "unknown"
    logger.info("booth_enrolled", source_ip=client)
    # The server's own .env has REDIS_HOST=localhost, useless to a remote booth.
    # Hand back the address the booth used to reach us instead.
    server_host = request.url.hostname or settings.redis_host
    return EnrollResponse(
        api_base_url=f"http://{server_host}:8000",
        internal_api_key=settings.internal_api_key,
        redis_host=server_host,
        redis_port=settings.redis_port,
    )


@router.post("/logout", response_model=SuccessResponse)
async def setup_logout(response: Response) -> SuccessResponse:
    """Clear setup session cookie (does not delete server row)."""
    _clear_setup_cookie(response)
    return SuccessResponse(message="Setup session cleared")


@router.post("/create-admin", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_admin(
    body: CreateAdminRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Create first admin during wizard. Refused if any admin already exists.

    On success, issues real auth cookies so subsequent CRUD endpoints work.
    """
    cookie = request.cookies.get(SETUP_COOKIE_NAME)
    session = await get_session_by_token(db, cookie) if cookie else None
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Setup session required",
        )

    if await has_any_admin(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin already exists. Use the standard login flow.",
        )

    user = User(
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role="admin",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tokens = await create_tokens(user)
    is_secure = get_settings().app_env == "production"
    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=1800,
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=604800,
    )

    logger.info("setup_admin_created", user_id=user.id)
    return UserResponse.model_validate(user)


@router.get("/preflight", response_model=PreflightResponse)
async def preflight(
    auth=Depends(require_setup_or_admin),
) -> PreflightResponse:
    """Run the existing scripts/preflight_check.py logic and return JSON."""
    sys.path.insert(0, str(get_settings().parking_install_root))
    try:
        from scripts import preflight_check  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - scripts may not import cleanly outside install
        try:
            import importlib.util
            from pathlib import Path

            script = Path(get_settings().parking_install_root) / "scripts" / "preflight_check.py"
            spec = importlib.util.spec_from_file_location("preflight_check", script)
            if spec is None or spec.loader is None:
                raise FileNotFoundError(str(script))
            preflight_check = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(preflight_check)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            logger.warning("preflight_unavailable", error=str(exc))
            return PreflightResponse(checks=[], passed=0, warnings=0, failed=0)

    try:
        runner = await preflight_check.run_all_checks()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.warning("preflight_runner_failed", error=str(exc))
        return PreflightResponse(checks=[], passed=0, warnings=0, failed=0)

    summary = runner.summary()
    return PreflightResponse(
        checks=[PreflightCheckResult(**c.to_dict()) for c in runner.checks],
        passed=summary.get("passed", 0),
        warnings=summary.get("warnings", 0),
        failed=summary.get("failed", 0),
    )


@router.post("/state", response_model=SuccessResponse)
async def save_state(
    body: SetupStateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    """Persist a wizard step's data for resume across reloads."""
    cookie = request.cookies.get(SETUP_COOKIE_NAME)
    session = await get_session_by_token(db, cookie) if cookie else None
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Setup session required",
        )
    await save_session_step(db, session, step=body.step, data=body.data)
    return SuccessResponse(message="Step saved", data={"step": body.step})


@router.get("/session", response_model=dict)
async def read_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return current session state for resume."""
    cookie = request.cookies.get(SETUP_COOKIE_NAME)
    session = await get_session_by_token(db, cookie) if cookie else None
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active setup session",
        )
    return {"current_step": session.current_step, "data": session.data}


# ────────────────────────────────────────────────────────────────────────
# Hardware probe / apply endpoints (P2)
# ────────────────────────────────────────────────────────────────────────


def _script_path(name: str) -> str:
    return str(Path(get_settings().parking_install_root) / "scripts" / name)


def _sudo_prefix() -> list[str]:
    """Return ['sudo', '-n'] when not running as root, else empty."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"]


@router.post("/detect-serial", response_model=DetectSerialResponse)
async def detect_serial(
    auth=Depends(require_setup_or_admin),
) -> DetectSerialResponse:
    """Run scripts/detect-serial-devices.sh --json (read-only, no root needed)."""
    cmd = ["bash", _script_path("detect-serial-devices.sh"), "--json"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20.0)
    except TimeoutError:
        proc.kill()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="detect-serial-devices.sh timed out",
        )

    try:
        payload = json.loads(stdout.decode("utf-8", errors="ignore") or "{}")
    except json.JSONDecodeError:
        logger.warning("detect_serial_bad_json", stderr=stderr.decode(errors="ignore"))
        return DetectSerialResponse(candidates=[])

    candidates = [
        DetectSerialCandidate(**c)
        for c in payload.get("candidates", [])
        if c.get("port")
    ]
    return DetectSerialResponse(candidates=candidates)


@router.post("/test-device", response_model=TestDeviceResponse)
async def test_device(
    body: TestDeviceRequest,
    auth=Depends(require_setup_or_admin),
) -> TestDeviceResponse:
    """Probe serial port / TCP endpoint / ping target — returns latency or error."""
    py = sys.executable or "python3"
    script = _script_path("test_device.py")
    args: list[str] = [py, script, body.type]

    if body.type == "serial":
        if not body.device:
            raise HTTPException(status_code=400, detail="device required for serial probe")
        args += ["--device", body.device, "--baudrate", str(body.baudrate or 9600)]
    elif body.type == "tcp":
        if not body.host or not body.port:
            raise HTTPException(status_code=400, detail="host and port required for tcp probe")
        args += ["--host", body.host, "--port", str(body.port)]
    else:  # ping
        if not body.host:
            raise HTTPException(status_code=400, detail="host required for ping")
        args += ["--host", body.host]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except TimeoutError:
        proc.kill()
        return TestDeviceResponse(ok=False, error="probe timed out after 10s")

    try:
        payload = json.loads(stdout.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return TestDeviceResponse(
            ok=False,
            error=stderr.decode("utf-8", errors="ignore").strip() or "probe returned non-JSON",
        )
    return TestDeviceResponse(**payload)


def _confirm_compass(host: str, port: int, timeout: float = 0.5) -> bool:
    """Blocking STAT probe — confirms the open port is actually a Compass
    controller, not some other device that happens to listen on 5000."""
    from protocols.compass.protocol import CompassTransport, cmd_stat

    transport = CompassTransport(host, port)
    try:
        transport.connect(timeout=timeout)
        return len(transport.send_recv(cmd_stat(), timeout=timeout)) > 0
    except OSError:
        return False
    finally:
        transport.close()


async def _scan_subnet(
    network: ipaddress.IPv4Network, port: int, *, connect_timeout: float = 0.3, concurrency: int = 64
) -> list[DiscoverGateCandidate]:
    """Concurrent TCP-open scan of every host in `network`, then a blocking
    STAT confirm on each hit. Bare open_connection (not subprocess-per-IP
    like test-device) since a /24 is 254 probes — subprocess doesn't scale."""
    sem = asyncio.Semaphore(concurrency)

    async def _probe(host: str) -> tuple[str, float] | None:
        async with sem:
            start = time.perf_counter()
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=connect_timeout
                )
            except (OSError, TimeoutError):
                return None
            latency = (time.perf_counter() - start) * 1000
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return host, latency

    hits = [r for r in await asyncio.gather(*(_probe(str(ip)) for ip in network.hosts())) if r]

    loop = asyncio.get_event_loop()
    return [
        DiscoverGateCandidate(
            host=host,
            latency_ms=round(latency, 2),
            confirmed=await loop.run_in_executor(None, _confirm_compass, host, port),
        )
        for host, latency in hits
    ]


@router.post("/discover-gates", response_model=DiscoverGatesResponse)
async def discover_gates(
    body: DiscoverGatesRequest,
    auth=Depends(require_setup_or_admin),
) -> DiscoverGatesResponse:
    """Scan a LAN subnet for open Compass controller ports, then confirm via STAT."""
    try:
        network = ipaddress.ip_network(body.subnet, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid subnet: {exc}")
    if network.num_addresses > 256:
        raise HTTPException(status_code=400, detail="subnet too large — max /24")

    candidates = await _scan_subnet(network, body.port)
    return DiscoverGatesResponse(candidates=candidates)


async def _wait_event(channel: str, want_type: str, timeout: float) -> tuple[bool, float, str | None]:
    """Subscribe to parking.events.<gate> and wait for an event of want_type.

    Returns (acked, elapsed_ms, error). On timeout, acked=False.
    """
    import time as _time

    await redis_client.connect()
    pubsub = redis_client.client.pubsub()
    try:
        await pubsub.subscribe(channel)
        t0 = _time.time()
        deadline = t0 + timeout
        while True:
            remaining = deadline - _time.time()
            if remaining <= 0:
                return False, (deadline - t0) * 1000, "timeout — no event from daemon"
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
            if msg is None:
                continue
            data = msg.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="ignore")
            try:
                payload = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("event_type") == want_type:
                return True, (_time.time() - t0) * 1000, None
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:
            pass


@router.post("/test-gate", response_model=TestGateResponse)
async def test_gate(
    body: TestGateRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_setup_or_admin),
) -> TestGateResponse:
    """End-to-end gate test: publish open command, wait for gate_opened ACK.

    For DUAL relay gates also publishes close + waits for gate_closed.
    Confirms the full pipeline (DB row → Redis Stream → daemon → controller →
    physical relay → daemon event publish) works as wired.
    """
    gate = await db.get(Gate, body.gate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail="Gate not found")
    if not gate.is_active:
        raise HTTPException(status_code=400, detail="Gate is not active")

    channel = f"parking.events.{gate.code}"
    steps: list[TestGateStep] = []

    # Open
    try:
        await publish_command(OpenGateCommand(gate_id=gate.code, reason="wizard_test"))
        sent = True
        err = None
    except Exception as e:
        sent, err = False, str(e)
    if not sent:
        steps.append(TestGateStep(action="open", sent=False, acked=False, error=err))
        return TestGateResponse(ok=False, gate_code=gate.code, steps=steps, error=err)

    acked, elapsed, err = await _wait_event(channel, "gate_opened", body.timeout_s)
    steps.append(TestGateStep(action="open", sent=True, acked=acked, elapsed_ms=elapsed, error=err))
    if not acked:
        return TestGateResponse(
            ok=False,
            gate_code=gate.code,
            steps=steps,
            error="open command sent but no gate_opened event — daemon down? controller unreachable?",
        )

    # Close (DUAL only — SINGLE relay auto-closes via close-sensor or timer)
    if gate.relay_mode == "DUAL":
        try:
            await publish_command(CloseGateCommand(gate_id=gate.code, reason="wizard_test"))
            await asyncio.sleep(0.5)  # give controller time to relay
            acked, elapsed, err = await _wait_event(channel, "gate_closed", body.timeout_s)
            steps.append(TestGateStep(action="close", sent=True, acked=acked, elapsed_ms=elapsed, error=err))
            if not acked:
                return TestGateResponse(
                    ok=False, gate_code=gate.code, steps=steps,
                    error="close command sent but no gate_closed event",
                )
        except Exception as e:
            steps.append(TestGateStep(action="close", sent=False, acked=False, error=str(e)))
            return TestGateResponse(ok=False, gate_code=gate.code, steps=steps, error=str(e))

    return TestGateResponse(ok=True, gate_code=gate.code, steps=steps)


@router.post("/write-udev", response_model=WriteUdevResponse)
async def write_udev(
    body: WriteUdevRequest,
    auth=Depends(require_setup_or_admin),
) -> WriteUdevResponse:
    """Write a single udev symlink rule, atomically, via the detection script."""
    cmd = [
        *_sudo_prefix(),
        "bash",
        _script_path("detect-serial-devices.sh"),
        "--write-udev",
        body.role,
        body.port,
    ]
    ok, stdout, stderr = await run_script_json(*cmd, timeout=15.0)
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return WriteUdevResponse(
            ok=False,
            error=(stderr.strip() or stdout.strip() or "udev write returned non-JSON"),
        )
    payload.setdefault("ok", ok)
    return WriteUdevResponse(**payload)


@router.post("/topology", response_model=SuccessResponse)
async def apply_topology(
    body: TopologyApplyRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_setup_or_admin),
) -> SuccessResponse:
    """Bulk-create gates so subsequent steps can configure each one."""
    # Idempotent: skip codes that already exist.
    result = await db.execute(select(Gate.code))
    existing = {row[0] for row in result.all()}

    created = 0
    for n in range(body.in_count):
        code = f"GIN-{n + 1:02d}"
        if code in existing:
            continue
        db.add(
            Gate(
                name=f"Pintu Masuk {n + 1}",
                code=code,
                direction="IN",
                protocol="compass",
                hardware_config={},
            )
        )
        created += 1
    for n in range(body.out_count):
        code = f"GOUT-{n + 1:02d}"
        if code in existing:
            continue
        db.add(
            Gate(
                name=f"Pintu Keluar {n + 1}",
                code=code,
                direction="OUT",
                protocol="compass",
                hardware_config={},
            )
        )
        created += 1
    await db.commit()
    return SuccessResponse(
        message=f"Topology applied ({created} new gate(s))",
        data={"created": created, "include_local_serial": body.include_local_serial},
    )


@router.post("/finalize", response_model=FinalizeResponse)
async def finalize(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_setup_or_admin),
) -> FinalizeResponse:
    """Run enable-gate-daemons.sh, flip setup_complete=true, delete session."""
    log: list[str] = []

    cookie = request.cookies.get(SETUP_COOKIE_NAME)
    session = await get_session_by_token(db, cookie) if cookie else None
    include_local = False
    if session is not None:
        include_local = bool(session.data.get("topology", {}).get("include_local_serial"))

    cmd = [
        *_sudo_prefix(),
        "bash",
        _script_path("enable-gate-daemons.sh"),
        "--run",
        "--json",
    ]
    if include_local:
        cmd.append("--include-local-serial")

    ok, stdout, stderr = await run_script_json(*cmd, timeout=120.0)
    log.extend([line for line in stdout.splitlines() if line.strip()])
    if stderr.strip():
        log.append(f"stderr: {stderr.strip()}")

    if not ok:
        logger.warning("setup_finalize_script_failed", stderr=stderr)
        return FinalizeResponse(ok=False, log=log, error="enable-gate-daemons.sh failed")

    await mark_setup_complete(db, complete=True)
    delete_setup_token()
    if session is not None:
        await delete_session(db, session)
    _clear_setup_cookie(response)
    logger.info("setup_finalized")
    return FinalizeResponse(ok=True, log=log)
