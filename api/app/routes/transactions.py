"""Transaction list routes (operator/admin)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.middleware.auth import require_operator
from api.app.models.parking_transaction import ParkingTransaction
from api.app.schemas.transaction import TransactionListItem
from api.app.utils.pagination import PaginationParams, paginated_list
from api.database import get_db
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("transaction_routes")

router = APIRouter(prefix="/transactions", tags=["Transactions"])


class TransactionListResponse(BaseModel):
    """Paginated transaction list — used by the admin grid for accurate totals."""

    items: list[TransactionListItem]
    total: int
    skip: int
    limit: int


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    pagination: PaginationParams = Depends(),
    status_filter: str | None = Query(None, alias="status"),
    payment_method: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> TransactionListResponse:
    """List parking transactions with optional filters.

    Returns a real total count so the frontend grid can render accurate
    pagination (page X of Y) instead of guessing from the result length.
    """
    # The response schema dereferences these relations; the model defaults to
    # lazy="noload" (to protect non-list call sites), so eager-load them here
    # in batched SELECTs instead of returning null display columns.
    stmt = (
        select(ParkingTransaction)
        .options(
            selectinload(ParkingTransaction.vehicle_type),
            selectinload(ParkingTransaction.gate_in),
            selectinload(ParkingTransaction.gate_out),
            selectinload(ParkingTransaction.shift),
            selectinload(ParkingTransaction.operator),
        )
        .order_by(ParkingTransaction.entry_time.desc())
    )

    if pagination.q:
        stmt = stmt.where(
            ParkingTransaction.barcode.ilike(f"%{pagination.q}%")
            | ParkingTransaction.card_number.ilike(f"%{pagination.q}%")
            | ParkingTransaction.plate_number.ilike(f"%{pagination.q}%")
        )

    if status_filter:
        stmt = stmt.where(ParkingTransaction.status == status_filter.upper())

    if payment_method:
        stmt = stmt.where(ParkingTransaction.payment_method == payment_method.upper())

    # `entry_time` is timestamptz (stored UTC). The picker sends bare local
    # dates, so build tz-aware bounds in the facility's operational timezone
    # (Asia/Jakarta) rather than letting Postgres cast a bare date at the DB
    # session timezone — otherwise day boundaries land on UTC midnight and
    # edge-of-day rows leak across days.
    tz = ZoneInfo(get_settings().app_timezone)
    if date_from:
        start = datetime.combine(date_from, time.min, tzinfo=tz)
        stmt = stmt.where(ParkingTransaction.entry_time >= start)

    if date_to:
        # Inclusive of the whole `date_to` day: upper bound is the start of the
        # next day in local time, so "s/d 2026-05-30" includes all of May 30.
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
        stmt = stmt.where(ParkingTransaction.entry_time < end)

    result = await paginated_list(
        db, stmt, skip=pagination.skip, limit=pagination.limit
    )
    return TransactionListResponse(
        items=[TransactionListItem.model_validate(t) for t in result.items],
        total=result.total,
        skip=result.skip,
        limit=result.limit,
    )


@router.get("/{tx_id}", response_model=TransactionListItem)
async def get_transaction(
    tx_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> TransactionListItem:
    """Get transaction by ID."""
    from fastapi import HTTPException, status

    result = await db.execute(
        select(ParkingTransaction)
        .options(
            selectinload(ParkingTransaction.vehicle_type),
            selectinload(ParkingTransaction.gate_in),
            selectinload(ParkingTransaction.gate_out),
            selectinload(ParkingTransaction.shift),
            selectinload(ParkingTransaction.operator),
        )
        .where(ParkingTransaction.id == tx_id)
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return TransactionListItem.model_validate(tx)
