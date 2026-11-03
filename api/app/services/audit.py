"""Audit logging service.

Provides helper functions for creating audit log entries.
Designed to be called from routes and services without blocking the main flow.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.audit_log import AuditLog
from shared.logging import get_logger

logger = get_logger("audit")


async def log_action(
    db: AsyncSession,
    *,
    action: str,
    user_id: int | None = None,
    username: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog | None:
    """Create an audit log entry.

    Args:
        db: Database session
        action: Action type (e.g. 'CASH_PAYMENT', 'SETTING_UPDATE')
        user_id: ID of user who performed the action
        username: Username for convenience
        entity_type: Type of entity affected (e.g. 'ParkingTransaction')
        entity_id: ID of affected entity
        details: Additional structured data
        ip_address: Client IP address
        user_agent: Client user agent string

    Returns:
        Created AuditLog or None if creation failed
    """
    try:
        log = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        # Savepoint: if the audit insert fails, only the audit work is rolled
        # back. A bare flush failure poisons the whole session and makes the
        # caller's later commit raise PendingRollbackError.
        async with db.begin_nested():
            db.add(log)
            await db.flush()
            await db.refresh(log)

        logger.info(
            "audit_log_created",
            action=action,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        return log

    except Exception as e:
        # Audit logging should never fail the main operation
        logger.error("audit_log_failed", action=action, error=str(e))
        return None
