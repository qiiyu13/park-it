"""Printer management routes — CRUD + paper counter operations."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin, require_auth
from api.app.models.printer import Printer
from api.database import get_db
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("printers_route")
router = APIRouter(prefix="/printers", tags=["printers"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PrinterCreateRequest(BaseModel):
    gate_id: str
    gate_type: str = "IN"
    name: str
    mode: str = "CONTROLLER_PASSTHROUGH"
    ip_address: str | None = None
    port: int | None = None
    serial_device: str | None = None
    baudrate: int = 9600
    paper_capacity: int = 300

    @field_validator("port", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class PrinterUpdateRequest(BaseModel):
    name: str | None = None
    mode: str | None = None
    ip_address: str | None = None
    port: int | None = None
    serial_device: str | None = None
    baudrate: int | None = None
    paper_capacity: int | None = None
    is_active: bool | None = None

    @field_validator("port", "baudrate", "paper_capacity", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        """The UI's number inputs submit "" when cleared — treat as unset."""
        if v == "" or v is None:
            return None
        return v


class PaperRefillRequest(BaseModel):
    count: int | None = None  # If None, reset to paper_capacity


class PrinterResponse(BaseModel):
    id: int
    gate_id: str
    gate_type: str
    name: str
    mode: str
    ip_address: str | None
    port: int | None
    serial_device: str | None
    baudrate: int
    paper_remaining: int
    paper_capacity: int
    last_refilled_at: datetime | None
    is_active: bool
    paper_status: str  # OK, WARNING, CRITICAL, EMPTY

    model_config = {"from_attributes": True}


def _paper_status(remaining: int) -> str:
    """Compute paper status from remaining count."""
    settings = get_settings()
    if not settings.printer_paper_counter_enabled:
        return "OK"
    if remaining <= 0:
        return "EMPTY"
    if remaining <= settings.printer_paper_critical_threshold:
        return "CRITICAL"
    if remaining <= settings.printer_paper_warning_threshold:
        return "WARNING"
    return "OK"


def _to_response(p: Printer) -> PrinterResponse:
    return PrinterResponse(
        id=p.id,
        gate_id=p.gate_id,
        gate_type=p.gate_type,
        name=p.name,
        mode=p.mode,
        ip_address=p.ip_address,
        port=p.port,
        serial_device=p.serial_device,
        baudrate=p.baudrate,
        paper_remaining=p.paper_remaining,
        paper_capacity=p.paper_capacity,
        last_refilled_at=p.last_refilled_at,
        is_active=p.is_active,
        paper_status=_paper_status(p.paper_remaining),
    )


# ---------------------------------------------------------------------------
# CRUD Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[PrinterResponse])
async def list_printers(
    gate_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """List all printers, optionally filtered by gate_id."""
    query = select(Printer).order_by(Printer.gate_id, Printer.name)
    if gate_id:
        query = query.where(Printer.gate_id == gate_id)

    result = await db.execute(query)
    printers = result.scalars().all()
    return [_to_response(p) for p in printers]


@router.post("/", response_model=PrinterResponse, status_code=status.HTTP_201_CREATED)
async def create_printer(
    req: PrinterCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Create a new printer."""
    printer = Printer(
        gate_id=req.gate_id,
        gate_type=req.gate_type,
        name=req.name,
        mode=req.mode,
        ip_address=req.ip_address,
        port=req.port,
        serial_device=req.serial_device,
        baudrate=req.baudrate,
        paper_capacity=req.paper_capacity,
        paper_remaining=req.paper_capacity,
    )
    db.add(printer)
    await db.commit()
    await db.refresh(printer)

    logger.info("printer_created", printer_id=printer.id, gate_id=req.gate_id)
    return _to_response(printer)


@router.get("/{printer_id}", response_model=PrinterResponse)
async def get_printer(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Get a single printer by ID."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return _to_response(printer)


@router.patch("/{printer_id}", response_model=PrinterResponse)
async def update_printer(
    printer_id: int,
    req: PrinterUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Update printer configuration."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(printer, field, value)

    await db.commit()
    await db.refresh(printer)

    logger.info("printer_updated", printer_id=printer_id)
    return _to_response(printer)


@router.delete("/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_printer(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Delete a printer."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")

    await db.delete(printer)
    await db.commit()

    logger.info("printer_deleted", printer_id=printer_id)


# ---------------------------------------------------------------------------
# Paper Counter Routes
# ---------------------------------------------------------------------------

@router.post("/{printer_id}/refill", response_model=PrinterResponse)
async def refill_paper(
    printer_id: int,
    req: PaperRefillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Record a paper refill.  Resets paper_remaining to given count or capacity."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")

    count = req.count if req.count is not None else printer.paper_capacity
    printer.paper_remaining = count
    printer.last_refilled_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(printer)

    logger.info(
        "paper_refilled",
        printer_id=printer_id,
        new_count=count,
    )
    return _to_response(printer)


@router.post("/{printer_id}/decrement", response_model=PrinterResponse)
async def decrement_paper(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Decrement paper counter by 1.  Called by print_worker after successful print."""
    settings = get_settings()
    if not settings.printer_paper_counter_enabled:
        raise HTTPException(status_code=400, detail="Paper counter is disabled")

    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(status_code=404, detail="Printer not found")

    if printer.paper_remaining > 0:
        printer.paper_remaining -= 1

    await db.commit()
    await db.refresh(printer)

    paper_status = _paper_status(printer.paper_remaining)
    if paper_status in ("CRITICAL", "EMPTY"):
        logger.warning(
            "paper_low",
            printer_id=printer_id,
            remaining=printer.paper_remaining,
            status=paper_status,
        )

    return _to_response(printer)


@router.post("/{printer_id}/test")
async def test_printer(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> dict:
    """Print a small test ticket through whichever transport answers.

    AUTO (and CONTROLLER_PASSTHROUGH) probe network → serial → controller in
    that order, so a technician can verify a freshly wired printer without
    touching the gate config.
    """
    printer = await db.get(Printer, printer_id)
    if printer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Printer not found")

    from workers.critical import print_worker as pw

    escpos = b"".join([
        b"\x1b\x61\x01",
        b"TEST PRINT\n",
        b"\x1b\x61\x00",
        f"Printer : {printer.name}\n".encode(),
        f"Gate    : {printer.gate_id}\n".encode(),
        b"E-Parking v2\n",
        b"\n\n\n\x1d\x56\x41",
    ])

    mode = (printer.mode or "AUTO").upper()
    if mode in ("AUTO", "CONTROLLER_PASSTHROUGH"):
        if pw._probe_network_printer(printer.ip_address, printer.port):
            mode = "NETWORK"
        elif pw._probe_serial_device(printer.serial_device):
            mode = "SERIAL"
        elif pw._probe_usb_printer(printer.serial_device):
            mode = "USB"
        else:
            mode = "CONTROLLER_PASSTHROUGH"

    config: dict = {}
    if mode == "NETWORK":
        if not printer.ip_address:
            raise HTTPException(status_code=400, detail="Printer has no IP address configured")
        config = {"printer_ip_address": printer.ip_address, "printer_port": printer.port or 9100}
    elif mode == "SERIAL":
        if not printer.serial_device:
            raise HTTPException(status_code=400, detail="Printer has no serial device configured")
        config = {"printer_device": printer.serial_device, "baudrate": printer.baudrate}
    elif mode == "USB":
        if not printer.serial_device:
            raise HTTPException(status_code=400, detail="Printer has no USB device path configured (/dev/usb/lp0)")
        config = {"printer_device": printer.serial_device}
    else:
        gate = (await db.execute(select(Gate).where(Gate.code == printer.gate_id))).scalar_one_or_none()
        if gate is None or not gate.controller_host:
            raise HTTPException(
                status_code=400,
                detail="Printer is not reachable by network/serial and its gate has no controller",
            )
        config = {
            "protocol": gate.protocol,
            "controller_host": gate.controller_host,
            "controller_port": gate.controller_port,
        }

    def _run() -> None:
        if mode == "NETWORK":
            pw._print_via_network(escpos, config)
        elif mode == "SERIAL":
            pw._print_via_serial(escpos, config)
        elif mode == "USB":
            pw._print_via_usb(escpos, config)
        else:
            pw._print_via_controller(escpos, config)

    try:
        await asyncio.to_thread(_run)
    except Exception as exc:
        logger.warning("printer_test_failed", printer_id=printer_id, mode=mode, error=str(exc))
        raise HTTPException(status_code=502, detail=f"{mode} print failed: {exc}"[:300])

    logger.info("printer_test_ok", printer_id=printer_id, mode=mode)
    return {"success": True, "mode": mode, "detail": f"Test print sent via {mode}"}


@router.get("/status/summary")
async def printer_status_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Dashboard summary of all printer paper statuses."""
    result = await db.execute(
        select(Printer).where(Printer.is_active == True).order_by(Printer.gate_id)  # noqa: E712
    )
    printers = result.scalars().all()

    summary = []
    for p in printers:
        ps = _paper_status(p.paper_remaining)
        summary.append({
            "printer_id": p.id,
            "gate_id": p.gate_id,
            "name": p.name,
            "paper_remaining": p.paper_remaining,
            "paper_capacity": p.paper_capacity,
            "status": ps,
            "last_refilled_at": p.last_refilled_at.isoformat() if p.last_refilled_at else None,
        })

    return {"printers": summary}
