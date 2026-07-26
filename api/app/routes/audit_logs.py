"""Audit log routes (admin-only)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin
from api.app.models.audit_log import AuditLog
from api.app.utils.pagination import PaginatedList, PaginationParams, paginated_list
from api.database import get_db

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("", dependencies=[Depends(require_admin)])
async def list_audit_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
    action: str | None = None,
    user_id: int | None = None,
    entity_type: str | None = None,
) -> PaginatedList:
    """List audit logs with optional filtering.

    Admin only.
    """
    query = select(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        query = query.where(AuditLog.action == action)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)

    return await paginated_list(db, query, skip=pagination.skip, limit=pagination.limit)
