"""Shared shift utilities."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.shift import Shift
from shared.config import get_settings


async def get_current_shift(db: AsyncSession) -> Shift | None:
    """Determine the current active shift based on local wall-clock time.

    Shift rows store local wall-clock times (e.g. 06:00-14:00), so the
    comparison must use the facility timezone, not UTC. Handles overnight
    shifts (e.g., 22:00 - 06:00).

    Args:
        db: Database session

    Returns:
        Current Shift or None when no active shift covers this time
    """
    tz = ZoneInfo(get_settings().app_timezone)
    now = datetime.now(tz).time()

    result = await db.execute(
        select(Shift)
        .where(Shift.is_active == True)  # noqa: E712
        .order_by(Shift.start_time)
    )
    shifts = result.scalars().all()

    for shift in shifts:
        start = shift.start_time
        end = shift.end_time

        if start <= end:
            if start <= now <= end:
                return shift
        else:
            if now >= start or now <= end:
                return shift

    # No fallback: returning shifts[0] masks "no shift covers now" and lets
    # payments be attributed to the wrong shift. Callers handle None.
    return None
