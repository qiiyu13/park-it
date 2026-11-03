"""Transaction service — creation, lookup, and completion of parking transactions.

This module handles the core database operations for parking transactions,
including entry creation, active transaction lookup, and exit completion.
"""

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models import AreaParkir, Gate, ParkingTransaction, VehicleType
from api.app.services.snapshot_utils import enqueue_snapshots_for_gate
from api.app.services.tariff import (
    DEFAULT_TARIFF_CONFIG,
    TariffConfig,
    VehicleTypeRate,
    calculate_tariff,
)
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("transaction_service")


async def create_entry_transaction(
    db: AsyncSession,
    *,
    barcode: str | None = None,
    card_number: str | None = None,
    plate_number: str | None = None,
    vehicle_type_id: int | None = None,
    gate_in_id: int | None = None,
    payment_method: Literal["CASH", "RFID_MEMBER", "EMONEY", "PENDING"] = "CASH",
    member_id: int | None = None,
) -> ParkingTransaction:
    """Create a new parking transaction at entry time.

    Args:
        db: Database session
        barcode: Ticket barcode (for CASH mode)
        card_number: RFID/e-money card number
        plate_number: License plate
        vehicle_type_id: Vehicle type FK
        gate_in_id: Gate-in FK
        payment_method: Payment method at entry
        member_id: Member FK (for RFID mode)

    Returns:
        Created ParkingTransaction
    """
    tx = ParkingTransaction(
        barcode=barcode,
        card_number=card_number,
        plate_number=plate_number,
        vehicle_type_id=vehicle_type_id,
        gate_in_id=gate_in_id,
        entry_time=datetime.now(UTC),
        payment_method=payment_method,
        member_id=member_id,
        status="ACTIVE",
    )
    db.add(tx)
    await db.flush()
    await db.refresh(tx)

    # Enqueue entry snapshot(s) for all cameras on this gate, and keep the
    # area occupancy counter in sync (atomic SQL, safe under concurrent lanes).
    if gate_in_id:
        gate = await db.get(Gate, gate_in_id)
        if gate:
            await enqueue_snapshots_for_gate(
                db=db,
                gate_code=gate.code,
                transaction_id=tx.id,
                snapshot_type="entry",
            )
            if gate.area_parkir_id:
                await db.execute(
                    update(AreaParkir)
                    .where(AreaParkir.id == gate.area_parkir_id)
                    .values(current=AreaParkir.current + 1)
                )

    logger.info(
        "transaction_created",
        transaction_id=tx.id,
        barcode=barcode,
        card_number=card_number,
        gate_in_id=gate_in_id,
    )
    return tx


async def find_active_transaction(
    db: AsyncSession,
    *,
    barcode: str | None = None,
    card_number: str | None = None,
    plate_number: str | None = None,
    for_update: bool = False,
) -> ParkingTransaction | None:
    """Find an active (uncompleted) parking transaction.

    Searches by barcode, card_number, or plate_number. Only one criterion
    should be provided; they are checked in order of specificity.

    Args:
        db: Database session
        barcode: Ticket barcode
        card_number: Card number
        plate_number: License plate

    Returns:
        Active ParkingTransaction or None
    """
    query = select(ParkingTransaction).where(ParkingTransaction.status == "ACTIVE")

    if barcode:
        query = query.where(ParkingTransaction.barcode == barcode)
    elif card_number:
        query = query.where(ParkingTransaction.card_number == card_number)
    elif plate_number:
        query = query.where(ParkingTransaction.plate_number == plate_number)
    else:
        return None

    if for_update:
        query = query.with_for_update()

    # Lookups can be by non-unique columns (plate_number is not unique, and a
    # vehicle may re-enter without exiting). Return the most recent active row
    # instead of raising MultipleResultsFound and 500-ing the exit lane.
    query = query.order_by(ParkingTransaction.entry_time.desc())

    result = await db.execute(query)
    return result.scalars().first()


async def get_vehicle_type_tariff_config(
    db: AsyncSession, vehicle_type_id: int | None
) -> tuple[TariffConfig, str | None]:
    """Build TariffConfig from database vehicle type rates.

    Returns:
        Tuple of (TariffConfig, vehicle_type_code) or (DEFAULT_TARIFF_CONFIG, None)
    """
    if vehicle_type_id is None:
        return DEFAULT_TARIFF_CONFIG, None

    result = await db.execute(
        select(VehicleType).where(VehicleType.id == vehicle_type_id)
    )
    vt = result.scalar_one_or_none()
    if vt is None:
        return DEFAULT_TARIFF_CONFIG, None

    # Build config from database rates. Pass every field through verbatim —
    # 0 means "not configured" and is handled inside the tariff engine
    # (daily_cap=0 → no cap; hourly_rate=0 → fall back to base_tariff).
    config = TariffConfig(
        vehicle_types={
            vt.code: VehicleTypeRate(
                hourly_rate=vt.hourly_rate,
                daily_cap=vt.max_daily_cap,
                base_tariff=vt.base_tariff,
                overnight_mode=vt.overnight_mode,
                overnight_tariff=vt.overnight_tariff,
                lost_ticket_penalty=vt.lost_ticket_penalty,
                is_progressive=vt.is_progressive,
            )
        },
        grace_period_minutes=15,
    )
    return config, vt.code


async def calculate_transaction_fee(
    db: AsyncSession,
    transaction: ParkingTransaction,
    exit_time: datetime | None = None,
    vehicle_type_id_override: int | None = None,
) -> int:
    """Calculate parking fee for a transaction.

    Args:
        db: Database session
        transaction: The parking transaction
        exit_time: Exit timestamp (defaults to now)
        vehicle_type_id_override: Use this vehicle type instead of the one on the transaction

    Returns:
        Fee in IDR
    """
    if exit_time is None:
        exit_time = datetime.now(UTC)

    effective_vt_id = vehicle_type_id_override if vehicle_type_id_override is not None else transaction.vehicle_type_id
    config, vt_code = await get_vehicle_type_tariff_config(db, effective_vt_id)

    # Default to MOBIL if no vehicle type found — log it so a broken/missing
    # vehicle_type FK is visible instead of silently charging car rates.
    if vt_code is None:
        logger.warning(
            "tariff_vehicle_type_missing",
            transaction_id=transaction.id,
            vehicle_type_id=effective_vt_id,
        )
        vt_code = "MOBIL"

    # Clock-skew guard: if the exit clock is behind the entry clock, clamp to a
    # zero-duration stay (fee 0) and log it instead of letting calculate_tariff
    # raise and silently fall through to a free exit.
    if exit_time < transaction.entry_time:
        logger.warning(
            "tariff_negative_duration",
            transaction_id=transaction.id,
            entry_time=transaction.entry_time.isoformat(),
            exit_time=exit_time.isoformat(),
        )
        exit_time = transaction.entry_time

    # Tariffs use local calendar boundaries ("midnight" overnight surcharge),
    # so convert both instants to the facility timezone before the engine sees
    # them. Duration is timezone-invariant; only the date crossing changes.
    tz = ZoneInfo(get_settings().app_timezone)
    try:
        fee = calculate_tariff(
            entry_time=transaction.entry_time.astimezone(tz),
            exit_time=exit_time.astimezone(tz),
            vehicle_type_code=vt_code,
            config=config,
            is_lost_ticket=transaction.is_lost_ticket,
        )
    except ValueError:
        # Genuine misconfiguration (unknown vehicle code) — surface it rather
        # than handing out a free exit. The caller turns this into an operator
        # error so the stay can be re-priced or escalated.
        logger.error(
            "tariff_calculation_failed",
            transaction_id=transaction.id,
            vehicle_type_code=vt_code,
        )
        raise

    return fee


async def complete_exit_transaction(
    db: AsyncSession,
    transaction: ParkingTransaction,
    *,
    gate_out_id: int,
    payment_method: Literal["CASH", "RFID_MEMBER", "EMONEY"],
    fee: int,
    paid_amount: int | None = None,
    member_id: int | None = None,
    emoney_transaction_id: int | None = None,
    operator_id: int | None = None,
    shift_id: int | None = None,
) -> ParkingTransaction:
    """Complete a parking transaction at exit.

    Args:
        db: Database session
        transaction: The active transaction to complete
        gate_out_id: Exit gate FK
        payment_method: Final payment method
        fee: Calculated fee
        paid_amount: Amount paid (for CASH)
        member_id: Member FK (for RFID)
        emoney_transaction_id: E-money transaction FK
        operator_id: Operator who processed payment
        shift_id: Assigned shift (gate_out_time)

    Returns:
        Updated ParkingTransaction
    """
    now = datetime.now(UTC)

    transaction.gate_out_id = gate_out_id
    transaction.exit_time = now
    transaction.payment_method = payment_method
    transaction.fee = fee
    transaction.paid_amount = paid_amount
    transaction.member_id = member_id
    transaction.emoney_transaction_id = emoney_transaction_id
    transaction.operator_id = operator_id
    transaction.shift_id = shift_id
    transaction.status = "COMPLETED"

    # Release one slot in the entry gate's area. GREATEST(...,0) prevents the
    # negative occupancy the legacy system was famous for when counters drift.
    if transaction.gate_in_id is not None:
        area_id = await db.scalar(
            select(Gate.area_parkir_id).where(Gate.id == transaction.gate_in_id)
        )
        if area_id is not None:
            await db.execute(
                update(AreaParkir)
                .where(AreaParkir.id == area_id)
                .values(current=func.greatest(AreaParkir.current - 1, 0))
            )

    await db.flush()
    await db.refresh(transaction)

    logger.info(
        "transaction_completed",
        transaction_id=transaction.id,
        payment_method=payment_method,
        fee=fee,
        gate_out_id=gate_out_id,
    )
    return transaction
