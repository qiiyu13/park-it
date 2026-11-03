"""Settlement routes."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    """Queue settlement file generation in the background worker.

    Previously this ran the whole generation (and its bank-facing SFTP
    enqueues) inline inside the HTTP request, blocking an API worker and
    timing out on large batches. The background worker owns the day-lock and
    the ARQ context, so enqueueing is the correct boundary.
    """
    from shared.redis import get_arq_redis

    try:
        arq = await get_arq_redis()
        await arq.enqueue_job(
            "generate_settlement_file",
            _queue_name="arq:queue:background",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Settlement queue unavailable: {e}",
        ) from e

    return SettlementTriggerResponse(
        status="queued",
        files_generated=0,
        total_transactions=0,
    )
