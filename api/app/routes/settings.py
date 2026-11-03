"""Settings routes."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin, require_auth
from api.app.models.setting import Setting
from api.app.schemas.setting import SettingResponse, SettingUpdate
from api.app.services.audit import log_action
from api.database import get_db
from shared.logging import get_logger

logger = get_logger("setting_routes")

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=list[SettingResponse])
async def list_settings(
    group: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> list[SettingResponse]:
    """List all settings."""
    query = select(Setting)
    if group:
        query = query.where(Setting.group == group)
    result = await db.execute(query)
    settings = result.scalars().all()
    return [SettingResponse.model_validate(s) for s in settings]


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_auth),
) -> SettingResponse:
    """Get setting by key."""
    from fastapi import HTTPException

    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    return SettingResponse.model_validate(setting)


@router.patch("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    data: SettingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SettingResponse:
    """Update a setting value."""
    from fastapi import HTTPException

    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")

    if setting.is_system and data.value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clear a system setting",
        )

    previous = setting.value
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(setting, field, value)

    try:
        user_id = int(current_user["sub"])
    except (KeyError, TypeError, ValueError):
        user_id = None
    await log_action(
        db,
        action="SETTING_UPDATE",
        user_id=user_id,
        username=current_user.get("username"),
        entity_type="Setting",
        entity_id=key,
        details={"old": previous, "new": setting.value},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    await db.refresh(setting)
    logger.info("setting_updated", key=key)
    return SettingResponse.model_validate(setting)
