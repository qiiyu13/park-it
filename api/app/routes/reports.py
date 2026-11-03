"""Report routes (admin only)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin
from api.app.models.emoney_transaction import EmoneyTransaction
from api.app.models.parking_transaction import ParkingTransaction
from api.app.models.shift import Shift
from api.app.models.site_config import SiteConfig
from api.app.models.user import User
from api.app.schemas.report import EmoneyReport, ShiftReport, ShiftReportItem, SummaryReport
from api.app.services.report_export import (
    export_summary_csv,
    export_summary_pdf,
    export_summary_xlsx,
)
from api.database import get_db
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("report_routes")

router = APIRouter(prefix="/reports", tags=["Reports"])


def _local_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Inclusive local-day bounds for a timestamptz column.

    Both endpoints of the picker are calendar days in the facility timezone;
    the upper bound is the start of the day after ``date_to`` (exclusive).
    """
    tz = ZoneInfo(get_settings().app_timezone)
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


@router.get("/summary", response_model=SummaryReport)
async def get_summary_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SummaryReport:
    """Get parking summary report for date range (both dates inclusive)."""
    start, end = _local_bounds(date_from, date_to)

    # Single query with conditional aggregation
    stmt = select(
        func.count(ParkingTransaction.id).label("total"),
        func.sum(ParkingTransaction.fee).label("total_revenue"),
        func.sum(case(
            (ParkingTransaction.payment_method == "CASH", ParkingTransaction.fee),
            else_=0,
        )).label("cash_revenue"),
        func.sum(case(
            (ParkingTransaction.payment_method == "EMONEY", ParkingTransaction.fee),
            else_=0,
        )).label("emoney_revenue"),
        func.sum(case(
            (ParkingTransaction.payment_method == "RFID_MEMBER", ParkingTransaction.fee),
            else_=0,
        )).label("rfid_revenue"),
        func.sum(case(
            (ParkingTransaction.status == "ACTIVE", 1),
            else_=0,
        )).label("active_count"),
        func.sum(case(
            (ParkingTransaction.status == "COMPLETED", 1),
            else_=0,
        )).label("completed_count"),
    ).where(
        ParkingTransaction.entry_time >= start,
        ParkingTransaction.entry_time < end,
    )

    result = await db.execute(stmt)
    row = result.one()

    total_transactions = row.total or 0
    total_revenue = row.total_revenue or 0
    avg_fee = total_revenue / total_transactions if total_transactions > 0 else 0

    return SummaryReport(
        total_transactions=total_transactions,
        total_revenue=total_revenue,
        cash_revenue=row.cash_revenue or 0,
        emoney_revenue=row.emoney_revenue or 0,
        rfid_revenue=row.rfid_revenue or 0,
        total_vehicles=total_transactions,
        average_fee=round(avg_fee, 2),
        active_transactions=row.active_count or 0,
        completed_transactions=row.completed_count or 0,
    )


@router.get("/emoney", response_model=EmoneyReport)
async def get_emoney_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> EmoneyReport:
    """Get e-money report for date range (both dates inclusive)."""
    start, end = _local_bounds(date_from, date_to)

    # Total e-money transactions
    total_stmt = select(func.count(EmoneyTransaction.id)).where(
        EmoneyTransaction.created_at >= start,
        EmoneyTransaction.created_at < end,
    )
    total_result = await db.execute(total_stmt)
    total_emoney = total_result.scalar() or 0

    # Total deducted
    deducted_stmt = select(func.sum(EmoneyTransaction.amount_deducted)).where(
        EmoneyTransaction.created_at >= start,
        EmoneyTransaction.created_at < end,
    )
    deducted_result = await db.execute(deducted_stmt)
    total_deducted = deducted_result.scalar() or 0

    # Status counts
    status_stmt = select(
        EmoneyTransaction.status,
        func.count(EmoneyTransaction.id),
    ).where(
        EmoneyTransaction.created_at >= start,
        EmoneyTransaction.created_at < end,
    ).group_by(EmoneyTransaction.status)
    status_result = await db.execute(status_stmt)

    success_count = 0
    failed_count = 0
    lost_contact_count = 0
    for status, count in status_result.all():
        if status == "SUCCESS":
            success_count = count
        elif status in ("FAILED", "CORRECTION_FAILED"):
            failed_count += count
        elif status == "LOST_CONTACT":
            lost_contact_count = count

    # Settlement counts
    settled_stmt = select(func.count(EmoneyTransaction.id)).where(
        EmoneyTransaction.created_at >= start,
        EmoneyTransaction.created_at < end,
        EmoneyTransaction.settlement_batch_id.isnot(None),
    )
    settled_result = await db.execute(settled_stmt)

    unsettled_stmt = select(func.count(EmoneyTransaction.id)).where(
        EmoneyTransaction.created_at >= start,
        EmoneyTransaction.created_at < end,
        EmoneyTransaction.settlement_batch_id.is_(None),
        EmoneyTransaction.status == "SUCCESS",
    )
    unsettled_result = await db.execute(unsettled_stmt)

    avg_deduct = total_deducted / total_emoney if total_emoney > 0 else 0

    return EmoneyReport(
        total_emoney_transactions=total_emoney,
        total_deducted=total_deducted,
        success_count=success_count,
        failed_count=failed_count,
        lost_contact_count=lost_contact_count,
        average_deduct_amount=round(avg_deduct, 2),
        unsettled_count=unsettled_result.scalar() or 0,
        settled_count=settled_result.scalar() or 0,
    )


@router.get("/shift", response_model=ShiftReport)
async def get_shift_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    shift_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> ShiftReport:
    """Get parking shift report for date range (both dates inclusive)."""
    tz_name = get_settings().app_timezone
    local_day = func.date(func.timezone(tz_name, ParkingTransaction.entry_time))

    query = select(
        Shift.id.label("shift_id"),
        Shift.name.label("shift_name"),
        local_day.label("date"),
        ParkingTransaction.operator_id,
        User.full_name.label("operator_name"),
        func.count(ParkingTransaction.id).label("total_transactions"),
        func.sum(ParkingTransaction.fee).label("total_revenue"),
        func.sum(
            case((ParkingTransaction.payment_method == "CASH", ParkingTransaction.fee), else_=0)
        ).label("cash_revenue"),
        func.sum(
            case((ParkingTransaction.payment_method == "EMONEY", ParkingTransaction.fee), else_=0)
        ).label("emoney_revenue"),
        func.sum(
            case((ParkingTransaction.payment_method == "RFID_MEMBER", ParkingTransaction.fee), else_=0)
        ).label("rfid_revenue"),
        func.sum(
            case((ParkingTransaction.status == "ACTIVE", 1), else_=0)
        ).label("active_transactions"),
        func.sum(
            case((ParkingTransaction.status == "COMPLETED", 1), else_=0)
        ).label("completed_transactions"),
    ).select_from(Shift).join(
        ParkingTransaction, ParkingTransaction.shift_id == Shift.id
    ).outerjoin(
        User, User.id == ParkingTransaction.operator_id
    ).where(
        # Compare local calendar dates on both bounds so the selected end day
        # is fully included (the summary endpoints use the same inclusive rule).
        local_day >= date_from,
        local_day <= date_to,
    ).group_by(
        Shift.id, Shift.name, local_day,
        ParkingTransaction.operator_id, User.full_name,
    )

    if shift_id:
        query = query.where(Shift.id == shift_id)

    result = await db.execute(query)
    rows = result.all()

    items = []
    total_revenue = 0
    total_transactions = 0

    for row in rows:
        item = ShiftReportItem(
            shift_id=row.shift_id,
            shift_name=row.shift_name,
            date=row.date,
            operator_id=row.operator_id,
            operator_name=row.operator_name,
            total_transactions=row.total_transactions or 0,
            total_revenue=row.total_revenue or 0,
            cash_revenue=row.cash_revenue or 0,
            emoney_revenue=row.emoney_revenue or 0,
            rfid_revenue=row.rfid_revenue or 0,
            active_transactions=row.active_transactions or 0,
            completed_transactions=row.completed_transactions or 0,
            average_fee=round(
                (row.total_revenue or 0) / max(row.total_transactions or 1, 1), 2
            ),
        )
        items.append(item)
        total_revenue += item.total_revenue
        total_transactions += item.total_transactions

    return ShiftReport(
        items=items,
        total_revenue=total_revenue,
        total_transactions=total_transactions,
    )


@router.get("/summary/daily", response_model=SummaryReport)
async def get_daily_report(
    report_date: date = Query(..., alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SummaryReport:
    """Get summary report for a single day."""
    return await get_summary_report(
        date_from=report_date,
        date_to=report_date,
        db=db,
        current_user=current_user,
    )


@router.get("/summary/weekly", response_model=SummaryReport)
async def get_weekly_report(
    year: int = Query(...),
    week: int = Query(..., ge=1, le=53),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SummaryReport:
    """Get summary report for an ISO week (Monday-Sunday)."""
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Year has no ISO week 53") from e

    return await get_summary_report(
        date_from=monday,
        date_to=monday + timedelta(days=6),
        db=db,
        current_user=current_user,
    )


@router.get("/summary/monthly", response_model=SummaryReport)
async def get_monthly_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SummaryReport:
    """Get summary report for a specific month."""
    from calendar import monthrange

    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    return await get_summary_report(
        date_from=start,
        date_to=end,
        db=db,
        current_user=current_user,
    )


@router.get("/summary/export")
async def export_summary(
    format: str = Query(..., pattern="^(csv|xlsx|pdf)$"),
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    """Export summary report in specified format."""
    report = await get_summary_report(
        date_from=date_from,
        date_to=date_to,
        db=db,
        current_user=current_user,
    )

    site_result = await db.execute(select(SiteConfig))
    site = site_result.scalar_one_or_none()
    site_name = site.name if site else "E-Parking"

    if format == "csv":
        content = export_summary_csv(report)
        media_type = "text/csv"
        ext = "csv"
    elif format == "xlsx":
        content = export_summary_xlsx(report)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    else:  # pdf
        content = export_summary_pdf(report, site_name, date_from, date_to)
        media_type = "application/pdf"
        ext = "pdf"

    filename = f"EParking_Report_Summary_{date_from}_{date_to}.{ext}"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
