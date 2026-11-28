"""Lost ticket (karcis hilang) at the exit POS — Compass "Denda Tiket Parkir Hilang".

The operator types ``xxxxx`` in the ticket box, fills the driver's identity,
and the stay becomes an ordinary ACTIVE transaction flagged ``is_lost_ticket``.
Payment, receipt, gate opening and snapshots then run the normal exit path.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_operator
from api.app.models import Gate, LostTicketReport, ParkingTransaction, Setting
from api.app.services.audit import log_action
from api.app.services.transaction import (
    calculate_transaction_fee_parts,
    lane_vehicle_type_id,
)
from api.database import get_db
from shared.config import get_settings

router = APIRouter(prefix="/lost-tickets", tags=["Lost Tickets"])

class LostTicketQuoteRequest(BaseModel):
    plate_number: str | None = Field(None, max_length=20)
    vehicle_type_id: int | None = None
    entry_time: datetime | None = None
    gate_out_id: int | None = None


class LostTicketCreateRequest(LostTicketQuoteRequest):
    plate_number: str = Field(..., min_length=1, max_length=20)
    gate_in_id: int | None = None
    driver_name: str = Field(..., min_length=1, max_length=100)
    id_number: str = Field(..., min_length=1, max_length=50)
    address: str | None = Field(None, max_length=200)
    rt_rw: str | None = Field(None, max_length=20)
    kelurahan: str | None = Field(None, max_length=100)
    kecamatan: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=255)


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


async def default_entry_time(db: AsyncSession, now: datetime | None = None) -> datetime:
    """Today's opening hour (setting ``lost_ticket_default_entry``), local time.

    Before opening (night shift) it is yesterday's opening hour, so the entry
    never lands after the exit.
    """
    raw = await db.scalar(select(Setting.value).where(Setting.key == "lost_ticket_default_entry"))
    try:
        hour, minute = (int(p) for p in str(raw or "").strip().split(":"))
        opening_time = time(hour, minute)
    except ValueError:
        opening_time = time(6, 0)
    now_local = (now or datetime.now(_tz())).astimezone(_tz())
    opening = datetime.combine(now_local.date(), opening_time, tzinfo=now_local.tzinfo)
    return opening if opening <= now_local else opening - timedelta(days=1)


def _plate(value: str | None) -> str | None:
    plate = (value or "").replace(" ", "").upper()[:20]
    return plate or None


async def _matched(db: AsyncSession, plate: str | None, *, for_update: bool = False):
    """Vehicle still parked under this plate (camera/RFID captured it at entry).

    Stored plates keep the operator's spaces ("H 2205 RR"), so compare without them.
    """
    if not plate:
        return None
    query = (
        select(ParkingTransaction)
        .where(
            ParkingTransaction.status == "ACTIVE",
            func.replace(func.upper(ParkingTransaction.plate_number), " ", "") == plate,
        )
        .order_by(ParkingTransaction.entry_time.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def _vehicle_type(db: AsyncSession, data: LostTicketQuoteRequest) -> int | None:
    if data.vehicle_type_id is not None:
        return data.vehicle_type_id
    return await lane_vehicle_type_id(db, data.gate_out_id)


@router.post("/quote")
async def quote(
    data: LostTicketQuoteRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
) -> dict:
    """TARIF and TARIF + DENDA for the form, without saving anything."""
    match = await _matched(db, _plate(data.plate_number))
    entry = match.entry_time if match else (data.entry_time or await default_entry_time(db))
    probe = ParkingTransaction(
        entry_time=entry,
        vehicle_type_id=await _vehicle_type(db, data),
        is_lost_ticket=True,
    )
    tariff, penalty = await calculate_transaction_fee_parts(db, probe)
    return {
        "matched": match is not None,
        "transaction_id": match.id if match else None,
        "gate_in_id": match.gate_in_id if match else None,
        "entry_time": entry.isoformat(),
        "default_entry_time": (await default_entry_time(db)).isoformat(),
        "tariff": tariff,
        "penalty": penalty,
        "total": tariff + penalty,
    }


@router.post("")
async def create(
    request: Request,
    data: LostTicketCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
) -> dict:
    """Record the lost ticket and return the transaction ready for payment.

    A plate still parked is reused (so its open ticket cannot exit later);
    otherwise a new stay starts at the estimated entry time.
    """
    plate = _plate(data.plate_number)
    if data.gate_in_id is not None:
        gate = await db.get(Gate, data.gate_in_id)
        if gate is None or gate.direction != "IN":
            raise HTTPException(status_code=400, detail="Gate masuk tidak valid")
    operator_id = int(user["sub"]) if user.get("sub") else None

    tx = await _matched(db, plate, for_update=True)
    matched = tx is not None
    if tx is None:
        tx = ParkingTransaction(
            entry_time=data.entry_time or await default_entry_time(db),
            gate_in_id=data.gate_in_id,
            plate_number=plate,
            status="ACTIVE",
            notes="Karcis hilang",
        )
        db.add(tx)
    tx.is_lost_ticket = True
    vehicle_type_id = await _vehicle_type(db, data)
    if vehicle_type_id is not None:
        tx.vehicle_type_id = vehicle_type_id
    await db.flush()

    report = await db.scalar(
        select(LostTicketReport).where(LostTicketReport.transaction_id == tx.id)
    )
    if report is None:
        report = LostTicketReport(transaction_id=tx.id)
        db.add(report)
    report.plate_number = plate
    report.driver_name = data.driver_name.strip()
    report.id_number = data.id_number.strip()
    for field in ("address", "rt_rw", "kelurahan", "kecamatan", "city", "notes"):
        value = getattr(data, field)
        setattr(report, field, value.strip() if value and value.strip() else None)
    report.operator_id = operator_id
    report.gate_out_id = data.gate_out_id
    await db.flush()
    if report.resi is None:
        # Compass style: date + running number (170420001).
        report.resi = f"{datetime.now(_tz()):%y%m%d}{report.id:04d}"
    if not tx.barcode:
        # Unique handle for the cash/e-money/reprint calls, which find the stay by barcode.
        tx.barcode = f"HILANG-{report.resi}"
    await db.flush()

    await log_action(
        db,
        action="LOST_TICKET",
        user_id=operator_id,
        username=user.get("username"),
        entity_type="ParkingTransaction",
        entity_id=str(tx.id),
        details={
            "resi": report.resi,
            "plate_number": plate,
            "driver_name": report.driver_name,
            "id_number": report.id_number,
            "entry_time": tx.entry_time.isoformat(),
            "matched_active_ticket": matched,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {"resi": report.resi, "barcode": tx.barcode, "transaction_id": tx.id}
