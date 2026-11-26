"""Help-button calls for the exit POS.

The entry daemon reports IN4 presses; the event consumer stores one open
HELP_REQUEST alert per gate. Every POS polls the open list (Compass checked
for emergencies every 5 s) and any operator can mark one handled.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_auth
from api.app.models.gate import Gate
from api.app.models.operator_alert import OperatorAlert
from api.database import get_db
from shared.logging import get_logger

logger = get_logger("operator_alert_routes")
router = APIRouter(prefix="/operator-alerts", tags=["Operator Alerts"])

HELP_REQUEST = "HELP_REQUEST"


@router.get("/help")
async def list_open_help_calls(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> list[dict]:
    """Unhandled help-button calls, oldest first."""
    rows = await db.execute(
        select(OperatorAlert, Gate)
        .outerjoin(Gate, Gate.id == OperatorAlert.gate_id)
        .where(OperatorAlert.alert_type == HELP_REQUEST, OperatorAlert.is_resolved == False)  # noqa: E712
        .order_by(OperatorAlert.created_at)
    )
    return [
        {
            "id": alert.id,
            "gate_code": gate.code if gate else None,
            "gate_name": gate.name if gate else None,
            "created_at": alert.created_at,
        }
        for alert, gate in rows.all()
    ]


@router.post("/{alert_id}/resolve")
async def resolve_help_call(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> dict:
    """Mark a help call handled; it disappears from every POS on the next poll."""
    alert = await db.get(OperatorAlert, alert_id)
    if alert is None or alert.alert_type != HELP_REQUEST:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not alert.is_resolved:
        alert.is_resolved = True
        alert.resolved_at = datetime.now(UTC)
        try:
            alert.resolved_by = int(current_user.get("sub"))
        except (TypeError, ValueError):
            alert.resolved_by = None
        await db.commit()
        logger.info("help_call_resolved", alert_id=alert_id, user_id=alert.resolved_by)
    return {"id": alert.id, "is_resolved": True}
