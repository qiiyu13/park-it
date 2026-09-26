"""Settlement routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from api.app.middleware.auth import require_admin
from api.app.models.emoney_settlement import EmoneySettlement
from api.app.schemas.settlement import (
    SettlementDetailResponse,
    SettlementListItem,
    SettlementTriggerResponse,
)
from api.database import get_db

router = APIRouter(prefix="/settlements", tags=["settlements"])


@router.get("", response_model=list[SettlementListItem])
async def list_settlements(
    request: Request,
    db=Depends(get_db),
    _: dict = Depends(require_admin),
    skip: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
):
    """List settlement files."""
    query = select(EmoneySettlement).order_by(EmoneySettlement.created_at.desc())
    if status_filter:
        query = query.where(EmoneySettlement.status == status_filter)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    settlements = result.scalars().all()
    return settlements


@router.get("/{settlement_id}", response_model=SettlementDetailResponse)
async def get_settlement(
    settlement_id: int,
    request: Request,
    db=Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Get settlement detail."""
    settlement = await db.get(EmoneySettlement, settlement_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    return settlement


@router.post("/trigger", response_model=SettlementTriggerResponse)
async def trigger_settlement(
    request: Request,
    db=Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Manually trigger settlement file generation.

    Passes the real ARQ redis in ctx — without it the day-lock is bypassed
    (double-settlement racing the 02:00 cron) and generated files are never
    enqueued for upload. The lockless path still exists for Redis outages
    (SKIP LOCKED protects), but here Redis is available by definition.
    """
    from shared.redis import get_arq_redis
    from workers.background.settlement_worker import generate_settlement_file

    try:
        ctx = {"redis": await get_arq_redis()}
    except Exception:
        ctx = {}
    result = await generate_settlement_file(ctx)
    return SettlementTriggerResponse(**result)
